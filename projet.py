#!/usr/bin/env python3
"""
projet.py — Un « projet » = une vidéo, sa transcription et ses sous-titres.

Les projets sont rangés dans ~/.soustitreur/projets/<id>.json. L'identifiant
dépend du NOM et de la TAILLE de la vidéo : redéposer la même vidéo rouvre le
projet existant au lieu de renvoyer le fichier à Aristote (gain de temps et de
crédits), même si elle a été déplacée entre-temps.

Contenu d'un projet :
  media            chemin de la vidéo
  audio            chemin de l'audio extrait (lecture de secours dans l'éditeur)
  enrichment_id    identifiant Aristote
  langue           langue de la transcription
  mots             mots horodatés (permettent de refaire le découpage)
  sous_titres      liste [{start, end, text}] : c'est ce que l'on corrige
  etat             envoi | attente | a_corriger | corrige | erreur
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402

import hashlib
import json
import os
import re
from datetime import datetime

import config as cfg
import sous_titres as st

DOSSIER_PROJETS = os.path.join(cfg.DOSSIER, "projets")
DOSSIER_AUDIO = os.path.join(cfg.DOSSIER, "audio")


def identifiant(chemin_media: str) -> str:
    nom = os.path.basename(chemin_media).lower()
    taille = os.path.getsize(chemin_media) if os.path.exists(chemin_media) else 0
    return hashlib.sha1(f"{nom}|{taille}".encode()).hexdigest()[:16]


def chemin_projet(pid: str) -> str:
    return os.path.join(DOSSIER_PROJETS, f"{pid}.json")


def existe(pid: str) -> bool:
    return os.path.exists(chemin_projet(pid))


def nouveau(chemin_media: str, langue: str) -> dict:
    return {
        "id": identifiant(chemin_media),
        "media": os.path.abspath(chemin_media),
        "nom": os.path.basename(chemin_media),
        "audio": "",
        "langue": langue,
        "enrichment_id": "",
        "mots": [],
        "sous_titres": [],
        "parametres": {},
        "etat": "envoi",
        "erreur": "",
        "cree": datetime.now().isoformat(timespec="seconds"),
        "modifie": datetime.now().isoformat(timespec="seconds"),
    }


def charger(pid: str) -> dict:
    with open(chemin_projet(pid), encoding="utf-8") as f:
        return json.load(f)


def enregistrer(p: dict) -> None:
    os.makedirs(DOSSIER_PROJETS, exist_ok=True)
    p["modifie"] = datetime.now().isoformat(timespec="seconds")
    tmp = chemin_projet(p["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False)
    os.replace(tmp, chemin_projet(p["id"]))


def lister() -> list[dict]:
    """Projets existants, du plus récent au plus ancien (sans les mots)."""
    sortie = []
    if not os.path.isdir(DOSSIER_PROJETS):
        return sortie
    for nom in os.listdir(DOSSIER_PROJETS):
        if nom.endswith(".json"):
            try:
                p = charger(nom[:-5])
                p.pop("mots", None)
                sortie.append(p)
            except (OSError, ValueError):
                pass
    return sorted(sortie, key=lambda p: p.get("modifie", ""), reverse=True)


def appliquer_transcription(p: dict, transcript: dict,
                            params: st.Parametres) -> None:
    """Remplit le projet à partir de la transcription d'Aristote."""
    mots = st.mots_depuis_aristote(transcript.get("sentences") or [],
                                   params.filtrer_hallucinations)
    p["mots"] = [[m.texte, round(m.debut, 3), round(m.fin, 3)] for m in mots]
    p["langue"] = transcript.get("language") or p.get("langue")
    redecouper(p, params)


def redecouper(p: dict, params: st.Parametres) -> None:
    """Refait le découpage depuis les mots (annule les corrections)."""
    mots = [st.Mot(t, d, f) for t, d, f in p.get("mots") or []]
    p["sous_titres"] = [s.en_dict() for s in st.decouper(mots, params)]
    p["parametres"] = params.en_dict()
    p["etat"] = "a_corriger"


def exporter(p: dict, formats: list[str], dossier: str | None = None) -> list[str]:
    """Écrit les fichiers à côté de la vidéo (ou dans `dossier`).

    Le projet doit être enregistré ensuite : il retient la liste des fichiers
    écrits (`exports`) pour pouvoir les remplacer lors d'un nouvel export.
    """
    sts = [st.SousTitre.depuis_dict(d) for d in p["sous_titres"]]
    base = os.path.splitext(p["nom"])[0]
    # « cours.fr.vtt » importé : on ne rajoute pas une seconde fois « .fr ».
    base = re.sub(r"\.(fr|en|es|de|it)$", "", base)
    dossier = dossier or p.get("dossier") or os.path.dirname(p.get("media") or "")
    if not dossier or not os.access(dossier, os.W_OK):
        dossier = os.path.join(os.path.expanduser("~"), "Documents")
    suffixe = f".{p.get('langue') or 'fr'}"
    deja = set(p.get("exports") or [])
    ecrits = []
    for fmt in formats:
        contenu = st.vers_vtt(sts) if fmt == "vtt" else st.vers_srt(sts)
        chemin = os.path.join(dossier, f"{base}{suffixe}.{fmt}")
        # Ne jamais écraser un fichier que SousTitreur n'a pas écrit lui-même
        # (le VTT d'origine importé depuis Pod, par exemple).
        if os.path.exists(chemin) and chemin not in deja:
            chemin = os.path.join(dossier, f"{base} (corrigé){suffixe}.{fmt}")
        with open(chemin, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenu)
        ecrits.append(chemin)
    p["exports"] = sorted(deja | set(ecrits))
    return ecrits
