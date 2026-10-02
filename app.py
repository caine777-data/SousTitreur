#!/usr/bin/env python3
"""
app.py — SousTitreur (interface graphique)
Université de Toulouse — MFCA

Déposez une vidéo : SousTitreur en extrait le son, l'envoie à Aristote,
récupère la transcription horodatée mot par mot, la découpe en sous-titres
conformes aux normes, puis ouvre l'éditeur de correction. Les fichiers VTT ou
SRT ne sont écrits qu'après relecture.

On peut aussi déposer un fichier VTT ou SRT existant (par exemple celui que
Pod a produit avec Aristote) pour le redécouper et le corriger, sans
renvoyer la vidéo.

Modules réutilisables sans interface (intégration future dans PodAdmin) :
  aristote_api.py   client de l'API Aristote
  sous_titres.py    découpage aux normes, export VTT / SRT
  projet.py         stockage des projets
  editeur.py        serveur local de l'éditeur (assets/editeur.html)
"""

from __future__ import annotations

__author__      = "Cédric MONNA"
__contact__     = "cedricmonna@gmail.com"
__institution__ = "Université de Toulouse — MFCA"
from __version__ import __version__   # noqa: E402  (source unique)
__copyright__   = "© Copyright 2026 Cédric MONNA"

import hashlib
import os
import queue
import subprocess
import sys
import threading
import traceback

import customtkinter as ctk
from tkinter import filedialog, messagebox

import config as cfg
import media
import projet as pj
import sous_titres as st
from aristote_api import AristoteAPI, AristoteErreur, ETATS
from editeur import ServeurEditeur

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

EXT_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".mpg", ".mpeg", ".flv"}
EXT_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
EXT_SOUS_TITRES = {".vtt", ".srt"}

LANGUES = {"Français": "fr", "Anglais": "en", "Espagnol": "es", "Allemand": "de",
           "Italien": "it", "Détection automatique": ""}

LIBELLES_ETAT = {
    "envoi": "Préparation",
    "attente": "Chez Aristote",
    "a_corriger": "À corriger",
    "corrige": "Exporté",
    "erreur": "Erreur",
}


def ouvrir_dossier(chemin: str) -> None:
    if sys.platform == "win32":
        os.startfile(chemin)                               # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


Base = ctk.CTk
if HAS_DND:
    class Base(ctk.CTk, TkinterDnD.DnDWrapper):            # type: ignore[no-redef]
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.TkdndVersion = TkinterDnD._require(self)


class App(Base):
    def __init__(self):
        super().__init__()
        self.cfg = cfg.charger()
        self.title(f"SousTitreur {__version__}")
        self.geometry("980x680")
        self.minsize(760, 520)
        ctk.set_appearance_mode("system")

        self.evenements: queue.Queue = queue.Queue()
        self.lignes: dict[str, dict] = {}
        self.envois = threading.Semaphore(2)          # 2 envois simultanés au plus
        self.serveur = ServeurEditeur(
            formats_defaut=lambda: self.cfg.get("formats", ["vtt"]),
            sur_enregistrement=lambda pid: self.evenements.put(("recharger", pid)))

        self._construire()
        self._charger_projets()
        self._reprendre_travaux()
        self.after(200, self._traiter_evenements)
        if not all(cfg.lire_identifiants()):
            self.after(400, lambda: (self.journal(
                "Première utilisation : renseignez vos identifiants Aristote."),
                self.ouvrir_reglages()))

    # ─────────────────────────── Interface ────────────────────────────
    def _construire(self):
        haut = ctk.CTkFrame(self, fg_color="transparent")
        haut.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(haut, text="SousTitreur", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        ctk.CTkLabel(haut, text="  Sous-titres Aristote aux normes, avec relecture",
                     text_color=("gray40", "gray65")).pack(side="left")
        ctk.CTkButton(haut, text="Réglages", width=100, command=self.ouvrir_reglages).pack(side="right")

        zone = ctk.CTkFrame(self, height=110, border_width=2, corner_radius=12,
                            border_color=("#b9a3c9", "#5a4670"))
        zone.pack(fill="x", padx=16, pady=6)
        zone.pack_propagate(False)
        texte = ("Déposez ici des vidéos ou des fichiers audio"
                 "\nou un fichier VTT / SRT existant à corriger")
        self.zone_label = ctk.CTkLabel(zone, text=texte, font=ctk.CTkFont(size=14))
        self.zone_label.pack(expand=True, side="left", padx=20)
        boutons = ctk.CTkFrame(zone, fg_color="transparent")
        boutons.pack(side="right", padx=16)
        ctk.CTkButton(boutons, text="Choisir des fichiers…", command=self.choisir).pack(pady=3)
        ctk.CTkButton(boutons, text="Reprendre un ID Aristote…", fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90"),
                      command=self.reprendre_id).pack(pady=3)
        if HAS_DND:
            for w in (zone, self.zone_label):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", lambda e: self.ajouter(self.tk.splitlist(e.data)))

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.pack(fill="x", padx=16, pady=(2, 6))
        ctk.CTkLabel(options, text="Langue parlée :").pack(side="left")
        inverse = {v: k for k, v in LANGUES.items()}
        self.langue = ctk.StringVar(value=inverse.get(self.cfg.get("langue", "fr"), "Français"))
        ctk.CTkOptionMenu(options, values=list(LANGUES), variable=self.langue, width=190,
                          command=lambda _: self._memoriser_langue()).pack(side="left", padx=8)

        ctk.CTkLabel(self, text="Vidéos", anchor="w",
                     font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=18)
        self.liste = ctk.CTkScrollableFrame(self)
        self.liste.pack(fill="both", expand=True, padx=16, pady=(2, 6))
        self.liste.grid_columnconfigure(0, weight=1)
        self.vide = ctk.CTkLabel(self.liste, text="Aucune vidéo pour l'instant.",
                                 text_color=("gray45", "gray60"))

        self.jr = ctk.CTkTextbox(self, height=90, font=ctk.CTkFont(size=12))
        self.jr.pack(fill="x", padx=16, pady=(0, 12))
        self.jr.configure(state="disabled")

    def journal(self, msg: str) -> None:
        self.jr.configure(state="normal")
        self.jr.insert("end", msg + "\n")
        self.jr.see("end")
        self.jr.configure(state="disabled")

    def _memoriser_langue(self):
        self.cfg["langue"] = LANGUES[self.langue.get()]
        cfg.enregistrer(self.cfg)

    # ─────────────────────── Liste des projets ────────────────────────
    def _charger_projets(self):
        for p in pj.lister()[:60]:
            self._ligne(p)
        self._maj_vide()

    def _maj_vide(self):
        if self.lignes:
            self.vide.grid_forget()
        else:
            self.vide.grid(row=0, column=0, pady=30)

    def _ligne(self, p: dict) -> None:
        pid = p["id"]
        if pid not in self.lignes:
            cadre = ctk.CTkFrame(self.liste)
            cadre.grid_columnconfigure(0, weight=1)
            nom = ctk.CTkLabel(cadre, text=p["nom"], anchor="w",
                               font=ctk.CTkFont(weight="bold"))
            nom.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
            etat = ctk.CTkLabel(cadre, text="", anchor="w", text_color=("gray35", "gray70"))
            etat.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
            barre = ctk.CTkProgressBar(cadre, height=6)
            barre.set(0)
            b_corr = ctk.CTkButton(cadre, text="Corriger", width=90,
                                   command=lambda: self.corriger(pid))
            b_exp = ctk.CTkButton(cadre, text="Exporter", width=90, fg_color="transparent",
                                  border_width=1, text_color=("gray10", "gray90"),
                                  command=lambda: self.exporter(pid))
            b_dos = ctk.CTkButton(cadre, text="Dossier", width=70, fg_color="transparent",
                                  border_width=1, text_color=("gray10", "gray90"),
                                  command=lambda: self.ouvrir_dossier_projet(pid))
            b_sup = ctk.CTkButton(cadre, text="✕", width=32, fg_color="transparent",
                                  text_color=("gray30", "gray70"), hover_color=("#f3d6d6", "#4a2525"),
                                  command=lambda: self.supprimer(pid))
            b_corr.grid(row=0, column=1, rowspan=2, padx=3)
            b_exp.grid(row=0, column=2, rowspan=2, padx=3)
            b_dos.grid(row=0, column=3, rowspan=2, padx=3)
            b_sup.grid(row=0, column=4, rowspan=2, padx=(3, 8))
            self.lignes[pid] = dict(cadre=cadre, etat=etat, barre=barre,
                                    corriger=b_corr, exporter=b_exp)
            self._reordonner(nouveau=pid)
        self._maj_ligne(p)
        self._maj_vide()

    def _reordonner(self, nouveau: str | None = None):
        ordre = list(self.lignes)
        if nouveau:                       # le plus récent en haut
            ordre.remove(nouveau)
            ordre.insert(0, nouveau)
            self.lignes = {k: self.lignes[k] for k in ordre}
        for i, pid in enumerate(self.lignes):
            self.lignes[pid]["cadre"].grid(row=i + 1, column=0, sticky="ew", pady=3)

    def _maj_ligne(self, p: dict, detail: str = "", progression: float | None = None):
        w = self.lignes.get(p["id"])
        if not w:
            return
        e = p.get("etat", "")
        texte = LIBELLES_ETAT.get(e, e)
        if e == "erreur" and p.get("erreur"):
            texte += " : " + p["erreur"]
        elif e in ("a_corriger", "corrige"):
            n = len(p.get("sous_titres") or [])
            prm = st.Parametres.depuis_dict(p.get("parametres"))
            revoir = sum(1 for d in p.get("sous_titres") or []
                         if st.verifier(st.SousTitre.depuis_dict(d), prm))
            texte += f" · {n} sous-titres"
            if revoir:
                texte += f", {revoir} à revoir"
        if detail:
            texte += " · " + detail
        w["etat"].configure(text=texte,
                            text_color=("#b3261e", "#ff8a80") if e == "erreur"
                            else ("gray35", "gray70"))
        pret = e in ("a_corriger", "corrige")
        w["corriger"].configure(state="normal" if pret else "disabled")
        w["exporter"].configure(state="normal" if pret else "disabled")
        if progression is None or pret or e == "erreur":
            w["barre"].grid_forget()
        else:
            w["barre"].grid(row=2, column=0, columnspan=5, sticky="ew", padx=10, pady=(0, 8))
            if progression < 0:
                w["barre"].configure(mode="indeterminate")
                w["barre"].start()
            else:
                w["barre"].stop()
                w["barre"].configure(mode="determinate")
                w["barre"].set(progression)

    # ─────────────────── Événements venant des threads ─────────────────
    def _traiter_evenements(self):
        try:
            while True:
                ev = self.evenements.get_nowait()
                genre = ev[0]
                if genre == "etat":
                    _, p, detail, prog = ev
                    self._ligne(p)
                    self._maj_ligne(p, detail, prog)
                elif genre == "journal":
                    self.journal(ev[1])
                elif genre == "recharger" and pj.existe(ev[1]):
                    self._maj_ligne(pj.charger(ev[1]))
                elif genre == "pret":
                    p = ev[1]
                    self._ligne(p)
                    self.journal(f"✔ {p['nom']} : transcription prête, "
                                 f"{len(p['sous_titres'])} sous-titres. Cliquez sur « Corriger ».")
                    self.bell()
        except queue.Empty:
            pass
        self.after(200, self._traiter_evenements)

    def _signaler(self, p: dict, detail: str = "", prog: float | None = None):
        self.evenements.put(("etat", dict(p), detail, prog))

    # ─────────────────────────── Ajout ────────────────────────────────
    def choisir(self):
        types = [("Vidéos, sons et sous-titres",
                  " ".join(f"*{e}" for e in sorted(EXT_VIDEO | EXT_AUDIO | EXT_SOUS_TITRES))),
                 ("Tous les fichiers", "*.*")]
        chemins = filedialog.askopenfilenames(title="Choisir des fichiers", filetypes=types)
        if chemins:
            self.ajouter(chemins)

    def ajouter(self, chemins):
        for c in chemins:
            ext = os.path.splitext(c)[1].lower()
            if ext in EXT_SOUS_TITRES:
                self.importer_sous_titres(c)
            elif ext in EXT_VIDEO | EXT_AUDIO:
                self.transcrire(c)
            else:
                self.journal(f"Ignoré (format non pris en charge) : {os.path.basename(c)}")

    def _client(self) -> AristoteAPI | None:
        cid, secret = cfg.lire_identifiants()
        if not (cid and secret):
            messagebox.showwarning("Identifiants manquants",
                                   "Renseignez d'abord l'identifiant et le secret Aristote "
                                   "dans les Réglages.")
            self.ouvrir_reglages()
            return None
        return AristoteAPI(cid, secret, self.cfg.get("url_aristote"))

    def _parametres(self) -> st.Parametres:
        return st.Parametres.depuis_dict(self.cfg.get("decoupage"))

    def transcrire(self, chemin: str):
        pid = pj.identifiant(chemin)
        if pj.existe(pid):
            ancien = pj.charger(pid)
            if ancien.get("etat") == "attente":
                self.journal(f"{ancien['nom']} est déjà en cours de transcription.")
                return
            if ancien.get("etat") in ("a_corriger", "corrige"):
                rep = messagebox.askyesnocancel(
                    "Vidéo déjà transcrite",
                    f"« {ancien['nom']} » a déjà été transcrite.\n\n"
                    "Oui : rouvrir la correction existante.\n"
                    "Non : renvoyer la vidéo à Aristote (les corrections seront perdues).")
                if rep is None:
                    return
                if rep:
                    ancien["media"] = os.path.abspath(chemin)     # si déplacée
                    pj.enregistrer(ancien)
                    self.corriger(pid)
                    return
        client = self._client()
        if not client:
            return
        p = pj.nouveau(chemin, LANGUES[self.langue.get()])
        pj.enregistrer(p)
        self._ligne(p)
        self.journal(f"→ {p['nom']} : préparation de l'envoi.")
        threading.Thread(target=self._travail, args=(client, p), daemon=True).start()

    def _travail(self, client: AristoteAPI, p: dict):
        try:
            ext = os.path.splitext(p["media"])[1].lower()
            with self.envois:
                a_envoyer = p["media"]
                if self.cfg.get("extraire_audio", True) and ext in EXT_VIDEO:
                    audio = os.path.join(pj.DOSSIER_AUDIO, f"{p['id']}.mp3")
                    self._signaler(p, "extraction du son", 0.0)
                    try:
                        if media.extraire_audio(p["media"], audio,
                                                lambda x: self._signaler(p, f"extraction du son {x:.0%}", x)):
                            p["audio"] = a_envoyer = audio
                    except Exception as e:                      # noqa: BLE001
                        # Repli : on envoie la vidéo entière (plus long, mais ça marche).
                        self.evenements.put(("journal",
                            f"  {p['nom']} : extraction du son impossible ({e}). "
                            "Envoi de la vidéo entière."))
                elif ext in EXT_AUDIO:
                    p["audio"] = p["media"]
                taille = os.path.getsize(a_envoyer)
                self._signaler(p, f"envoi à Aristote ({taille / 1e6:.0f} Mo)", 0.0)
                p["enrichment_id"] = client.envoyer_fichier(
                    a_envoyer, p["langue"] or None, nom_original=p["nom"],
                    progression=lambda lu, tot: self._signaler(
                        p, f"envoi à Aristote {lu / max(tot, 1):.0%}", lu / max(tot, 1)))
            p["etat"] = "attente"
            pj.enregistrer(p)
            self.evenements.put(("journal", f"  {p['nom']} : envoyé (ID Aristote {p['enrichment_id']})."))
            self._attendre_et_recuperer(client, p)
        except Exception as e:                                  # noqa: BLE001
            self._echec(p, e)

    def _attendre_et_recuperer(self, client: AristoteAPI, p: dict):
        try:
            self._signaler(p, "en attente d'Aristote", -1)
            d = client.attendre(
                p["enrichment_id"],
                rappel=lambda s, _d: self._signaler(p, ETATS.get(s, s), -1))
            self._signaler(p, "récupération de la transcription", -1)
            tr = client.transcription(p["enrichment_id"], d.get("initialVersionId"))
            pj.appliquer_transcription(p, tr, self._parametres())
            pj.enregistrer(p)
            self.evenements.put(("pret", dict(p)))
        except Exception as e:                                  # noqa: BLE001
            self._echec(p, e)

    def _echec(self, p: dict, e: Exception):
        p["etat"] = "erreur"
        p["erreur"] = str(e) if isinstance(e, (AristoteErreur, RuntimeError, OSError)) \
            else f"{type(e).__name__} : {e}"
        pj.enregistrer(p)
        self._signaler(p)
        self.evenements.put(("journal", f"✖ {p['nom']} : {p['erreur']}"))
        if not isinstance(e, (AristoteErreur, RuntimeError, OSError)):
            self.evenements.put(("journal", traceback.format_exc(limit=3)))

    def _reprendre_travaux(self):
        """Au démarrage : relance le suivi des vidéos restées chez Aristote."""
        for p in pj.lister():
            if p.get("etat") == "envoi":
                p = pj.charger(p["id"])
                p["etat"], p["erreur"] = "erreur", "envoi interrompu, redéposez la vidéo"
                pj.enregistrer(p)
                self._maj_ligne(p)
            elif p.get("etat") == "attente" and p.get("enrichment_id"):
                cid, secret = cfg.lire_identifiants()
                if cid and secret:
                    client = AristoteAPI(cid, secret, self.cfg.get("url_aristote"))
                    self.journal(f"Reprise du suivi : {p['nom']}")
                    threading.Thread(target=self._attendre_et_recuperer,
                                     args=(client, pj.charger(p["id"])), daemon=True).start()

    def reprendre_id(self):
        """Récupère une transcription déjà faite par Aristote (par exemple via Pod)."""
        client = self._client()
        if not client:
            return
        dlg = ctk.CTkInputDialog(title="Reprendre un ID Aristote",
                                 text="Identifiant de l'enrichissement Aristote\n"
                                      "(format 1234abcd-…, visible dans l'admin de Pod) :")
        eid = (dlg.get_input() or "").strip()
        if not eid:
            return
        video = filedialog.askopenfilename(
            title="Vidéo correspondante, pour la relecture (Annuler si vous ne l'avez pas)",
            filetypes=[("Vidéos", " ".join(f"*{e}" for e in sorted(EXT_VIDEO | EXT_AUDIO)))])
        if video:
            p = pj.nouveau(video, LANGUES[self.langue.get()])
        else:
            p = pj.nouveau(f"Aristote {eid[:8]}", LANGUES[self.langue.get()])
            p["id"] = hashlib.sha1(eid.encode()).hexdigest()[:16]
            p["media"] = ""
        p["enrichment_id"] = eid
        p["etat"] = "attente"
        pj.enregistrer(p)
        self._ligne(p)
        threading.Thread(target=self._attendre_et_recuperer, args=(client, p), daemon=True).start()

    def importer_sous_titres(self, chemin: str):
        """Crée un projet à partir d'un VTT / SRT existant, puis le redécoupe."""
        try:
            with open(chemin, encoding="utf-8-sig") as f:
                sts = st.lire_vtt_srt(f.read())
        except (OSError, UnicodeDecodeError) as e:
            self.journal(f"✖ Lecture impossible de {os.path.basename(chemin)} : {e}")
            return
        if not sts:
            self.journal(f"✖ Aucun sous-titre trouvé dans {os.path.basename(chemin)}.")
            return
        # Vidéo du même nom dans le même dossier (« cours.fr.vtt » → « cours.mp4 »).
        dossier, nom = os.path.split(chemin)
        base = nom.rsplit(".", 1)[0]
        bases = {base, base.rsplit(".", 1)[0]}
        video = next((os.path.join(dossier, f) for f in os.listdir(dossier)
                      if os.path.splitext(f)[1].lower() in EXT_VIDEO | EXT_AUDIO
                      and os.path.splitext(f)[0] in bases), "")
        p = pj.nouveau(video or chemin, LANGUES[self.langue.get()])
        # Identifiant tiré du fichier de sous-titres : ne remplace jamais le
        # projet d'une transcription Aristote de la même vidéo.
        p["id"] = pj.identifiant(chemin)
        p["nom"] = nom
        p["dossier"] = dossier
        if not video:
            p["media"] = ""
        phrases = [{"text": s.texte.replace("\n", " "), "start": s.debut, "end": s.fin}
                   for s in sts]
        pj.appliquer_transcription(p, {"sentences": phrases, "language": p["langue"]},
                                   self._parametres())
        pj.enregistrer(p)
        self._ligne(p)
        self.journal(f"✔ {nom} importé et redécoupé : {len(sts)} → "
                     f"{len(p['sous_titres'])} sous-titres."
                     + ("" if video else " Aucune vidéo du même nom trouvée à côté."))
        self.corriger(p["id"])

    # ─────────────────────────── Actions ──────────────────────────────
    def corriger(self, pid: str):
        self.serveur.ouvrir(pid)
        self.journal("Éditeur ouvert dans le navigateur. Les corrections sont "
                     "enregistrées automatiquement.")

    def exporter(self, pid: str):
        p = pj.charger(pid)
        prm = st.Parametres.depuis_dict(p.get("parametres"))
        revoir = sum(1 for d in p["sous_titres"]
                     if st.verifier(st.SousTitre.depuis_dict(d), prm))
        if p.get("etat") != "corrige" and not messagebox.askyesno(
                "Exporter sans relecture",
                "Ces sous-titres n'ont pas été relus dans l'éditeur"
                + (f" et {revoir} ne respectent pas la norme" if revoir else "")
                + ".\n\nExporter quand même ?"):
            return
        fichiers = pj.exporter(p, self.cfg.get("formats", ["vtt"]))
        p["etat"] = "corrige"
        pj.enregistrer(p)
        self._maj_ligne(p)
        for f in fichiers:
            self.journal(f"✔ Écrit : {f}")

    def ouvrir_dossier_projet(self, pid: str):
        p = pj.charger(pid)
        dossier = p.get("dossier") or os.path.dirname(p.get("media") or "")
        ouvrir_dossier(dossier if os.path.isdir(dossier) else os.path.expanduser("~"))

    def supprimer(self, pid: str):
        p = pj.charger(pid)
        if not messagebox.askyesno(
                "Retirer de la liste",
                f"Retirer « {p['nom']} » de SousTitreur ?\n\nLes corrections non exportées "
                "seront perdues. La vidéo et les fichiers déjà exportés ne sont pas touchés."):
            return
        for f in (pj.chemin_projet(pid),
                  os.path.join(pj.DOSSIER_AUDIO, f"{pid}.mp3")):
            try:
                os.remove(f)
            except OSError:
                pass
        w = self.lignes.pop(pid, None)
        if w:
            w["cadre"].destroy()
        self._reordonner()
        self._maj_vide()

    # ─────────────────────────── Réglages ─────────────────────────────
    def ouvrir_reglages(self):
        FenetreReglages(self)


class FenetreReglages(ctk.CTkToplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Réglages")
        self.geometry("520x620")
        self.transient(app)
        self.after(50, self.grab_set)
        c = app.cfg
        prm = st.Parametres.depuis_dict(c.get("decoupage"))
        cid, secret = cfg.lire_identifiants()

        f = ctk.CTkScrollableFrame(self)
        f.pack(fill="both", expand=True, padx=12, pady=12)
        f.grid_columnconfigure(1, weight=1)
        r = 0

        def titre(t):
            nonlocal r
            ctk.CTkLabel(f, text=t, font=ctk.CTkFont(weight="bold"), anchor="w").grid(
                row=r, column=0, columnspan=2, sticky="ew", pady=(12, 4))
            r += 1

        def champ(libelle, valeur, masque=False, largeur=None):
            nonlocal r
            ctk.CTkLabel(f, text=libelle, anchor="w").grid(row=r, column=0, sticky="w", pady=3)
            e = ctk.CTkEntry(f, show="•" if masque else "", width=largeur or 260)
            e.insert(0, str(valeur))
            e.grid(row=r, column=1, sticky="w" if largeur else "ew", pady=3, padx=(8, 0))
            r += 1
            return e

        titre("Connexion à Aristote")
        self.e_url = champ("Adresse de l'API", c.get("url_aristote", ""))
        self.e_id = champ("Identifiant client", cid)
        self.e_secret = champ("Secret client", secret, masque=True)
        ctk.CTkLabel(f, text="Identifiants fournis avec l'application : rien à modifier.\n"
                             "Si vous en saisissez d'autres, ils sont rangés dans le "
                             "coffre-fort de Windows ou macOS.",
                     text_color=("gray40", "gray65"), justify="left", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.b_test = ctk.CTkButton(f, text="Tester la connexion", command=self.tester, width=160)
        self.b_test.grid(row=r, column=0, sticky="w", pady=6)
        self.l_test = ctk.CTkLabel(f, text="", anchor="w", wraplength=300, justify="left")
        self.l_test.grid(row=r, column=1, sticky="ew", padx=8)
        r += 1

        titre("Normes des sous-titres")
        self.e_cpl = champ("Caractères par ligne", prm.car_par_ligne, largeur=80)
        self.e_lignes = champ("Lignes par sous-titre", prm.lignes_max, largeur=80)
        self.e_dmin = champ("Durée minimale (s)", prm.duree_min, largeur=80)
        self.e_dmax = champ("Durée maximale (s)", prm.duree_max, largeur=80)
        self.e_cps = champ("Vitesse de lecture max. (car./s)", prm.cps_max, largeur=80)

        titre("Export et envoi")
        formats = c.get("formats", ["vtt"])
        self.v_vtt = ctk.BooleanVar(value="vtt" in formats)
        self.v_srt = ctk.BooleanVar(value="srt" in formats)
        self.v_audio = ctk.BooleanVar(value=c.get("extraire_audio", True))
        ctk.CTkCheckBox(f, text="Créer un fichier VTT (Pod, Moodle, web)", variable=self.v_vtt).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=3); r += 1
        ctk.CTkCheckBox(f, text="Créer un fichier SRT (montage, YouTube)", variable=self.v_srt).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=3); r += 1
        ctk.CTkCheckBox(f, text="N'envoyer que le son à Aristote (bien plus rapide)",
                        variable=self.v_audio).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        r += 1

        bas = ctk.CTkFrame(self, fg_color="transparent")
        bas.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(bas, text="Enregistrer", command=self.enregistrer).pack(side="right")
        ctk.CTkButton(bas, text="Annuler", fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.destroy).pack(side="right", padx=8)
        ctk.CTkLabel(bas, text=f"SousTitreur {__version__} · {__copyright__}",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).pack(side="left")

    def tester(self):
        self.l_test.configure(text="Test en cours…", text_color=("gray30", "gray70"))
        client = AristoteAPI(self.e_id.get(), self.e_secret.get(), self.e_url.get())

        def fil():
            try:
                msg, ok = client.tester(), True
            except Exception as e:                              # noqa: BLE001
                msg, ok = str(e), False
            self.after(0, lambda: self.l_test.configure(
                text=msg, text_color=("#1f7a3a", "#5cc47c") if ok else ("#b3261e", "#ff8a80")))
        threading.Thread(target=fil, daemon=True).start()

    def enregistrer(self):
        try:
            decoupage = {
                "car_par_ligne": int(self.e_cpl.get()),
                "lignes_max": int(self.e_lignes.get()),
                "duree_min": float(self.e_dmin.get().replace(",", ".")),
                "duree_max": float(self.e_dmax.get().replace(",", ".")),
                "cps_max": float(self.e_cps.get().replace(",", ".")),
            }
        except ValueError:
            messagebox.showerror("Valeur incorrecte", "Les normes doivent être des nombres.", parent=self)
            return
        formats = [x for x, v in (("vtt", self.v_vtt), ("srt", self.v_srt)) if v.get()] or ["vtt"]
        c = self.app.cfg
        c.update(url_aristote=self.e_url.get().strip() or cfg.DEFAUTS["url_aristote"],
                 decoupage=decoupage, formats=formats, extraire_audio=self.v_audio.get())
        cfg.enregistrer(c)
        if self.e_id.get().strip() and self.e_secret.get().strip():
            try:
                cfg.ecrire_identifiants(self.e_id.get(), self.e_secret.get())
            except Exception as e:                              # noqa: BLE001
                messagebox.showerror("Coffre-fort indisponible", str(e), parent=self)
                return
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
