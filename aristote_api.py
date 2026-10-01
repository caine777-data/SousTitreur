#!/usr/bin/env python3
"""
aristote_api.py — Client minimal de l'API Aristote (CentraleSupélec).

Module SANS interface graphique : réutilisable tel quel dans PodAdmin.

Documentation de l'API : https://api.aristote.education/api/doc
Authentification : OAuth2 « client credentials » (client_id + client_secret),
les mêmes identifiants que ceux configurés dans Pod
(AI_ENRICHMENT_CLIENT_ID / AI_ENRICHMENT_CLIENT_SECRET).

Parcours pour obtenir une transcription :
  1. `envoyer_fichier()`       → identifiant d'enrichissement
  2. `etat()` en boucle         → jusqu'à ce que la transcription soit prête
  3. `transcription()`          → phrases horodatées, mot par mot

On demande UNIQUEMENT la transcription (pas de métadonnées, pas de quiz) :
c'est plus rapide et cela ne consomme pas de génération par l'IA.
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402

import json
import mimetypes
import os
import time
from typing import Callable

import requests

try:
    from requests_toolbelt.multipart.encoder import (MultipartEncoder,
                                                     MultipartEncoderMonitor)
    HAS_TOOLBELT = True
except Exception:
    HAS_TOOLBELT = False

URL_DEFAUT = "https://stt.ilaas.fr/api"          # instance ILaaS (Université de Toulouse)
VERSION_API = "v1"

# États renvoyés par Aristote, avec un libellé lisible.
ETATS = {
    "WAITING_MEIDA_UPLOAD": "En attente du fichier",      # (faute d'origine)
    "WAITING_MEDIA_UPLOAD": "En attente du fichier",
    "UPLOADING_MEDIA": "Réception du fichier",
    "WAITING_MEDIA_TRANSCRIPTION": "En file d'attente",
    "TRANSCRIBING_MEDIA": "Transcription en cours",
    "WAITING_AI_ENRICHMENT": "Transcription terminée",
    "AI_ENRICHING": "Transcription terminée",
    "WAITING_TRANSLATION": "Transcription terminée",
    "TRANSLATING": "Traduction en cours",
    "WAITING_AI_EVALUATION": "Transcription terminée",
    "AI_EVALUATING": "Transcription terminée",
    "SUCCESS": "Transcription terminée",
    "FAILURE": "Échec",
}
# États où la transcription n'existe pas encore.
ETATS_AVANT_TRANSCRIPTION = {
    "WAITING_MEIDA_UPLOAD", "WAITING_MEDIA_UPLOAD", "UPLOADING_MEDIA",
    "WAITING_MEDIA_TRANSCRIPTION", "TRANSCRIBING_MEDIA",
}


class AristoteErreur(Exception):
    pass


def _message_erreur(r: requests.Response) -> str:
    try:
        d = r.json()
        errs = d.get("errors") or []
        if errs:
            return " ; ".join(
                str(e.get("message") or next(iter(e.values()), "")) for e in errs)
        return str(d)[:300]
    except ValueError:
        return (r.text or "")[:300]


class AristoteAPI:
    def __init__(self, client_id: str, client_secret: str,
                 url: str = URL_DEFAUT, timeout: int = 60):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.url = (url or URL_DEFAUT).rstrip("/")
        self.timeout = timeout
        self._jeton: str | None = None
        self._expire = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"SousTitreur/{__version__}"

    # ── Authentification ────────────────────────────────────────────────
    def jeton(self) -> str:
        if self._jeton and time.time() < self._expire - 60:
            return self._jeton
        r = self.session.post(
            f"{self.url}/token",
            json={"grant_type": "client_credentials",
                  "client_id": self.client_id,
                  "client_secret": self.client_secret},
            headers={"Accept": "application/json"},
            timeout=self.timeout)
        if r.status_code != 200:
            raise AristoteErreur(
                f"Connexion refusée par Aristote ({r.status_code}) : "
                f"{_message_erreur(r)}. Vérifiez l'identifiant et le secret.")
        d = r.json()
        self._jeton = d["access_token"]
        self._expire = time.time() + float(d.get("expires_in", 3600))
        return self._jeton

    def _entetes(self) -> dict:
        return {"Authorization": f"Bearer {self.jeton()}",
                "Accept": "application/json"}

    def _get(self, chemin: str, **kw) -> requests.Response:
        r = self.session.get(f"{self.url}/{VERSION_API}{chemin}",
                             headers=self._entetes(), timeout=self.timeout, **kw)
        if r.status_code == 401:                      # jeton expiré entre-temps
            self._jeton = None
            r = self.session.get(f"{self.url}/{VERSION_API}{chemin}",
                                 headers=self._entetes(), timeout=self.timeout, **kw)
        if r.status_code != 200:
            raise AristoteErreur(f"Aristote {r.status_code} sur {chemin} : "
                                 f"{_message_erreur(r)}")
        return r

    # ── Diagnostic ──────────────────────────────────────────────────────
    def tester(self) -> str:
        """Vérifie les identifiants. Renvoie un court compte rendu."""
        self.jeton()
        modeles = self._get("/enrichments/ai_model_infrastructure_combinations").json()
        noms = ", ".join(sorted({m.get("aiModel", "?") for m in modeles})) or "aucun"
        return f"Connexion réussie. Modèles d'IA proposés : {noms}."

    # ── Envoi ───────────────────────────────────────────────────────────
    def envoyer_fichier(self, chemin: str, langue: str | None = "fr",
                        nom_original: str | None = None,
                        progression: Callable[[int, int], None] | None = None,
                        identifiant_utilisateur: str | None = None) -> str:
        """Envoie une vidéo ou un fichier audio. Renvoie l'ID d'enrichissement."""
        parametres = {
            "generateMetadata": False,
            "generateQuiz": False,
            "generateNotes": False,
        }
        if langue:
            parametres["language"] = langue
        nom = nom_original or os.path.basename(chemin)
        mime = mimetypes.guess_type(chemin)[0] or "application/octet-stream"
        # Aristote refuse un envoi sans adresse de notification. On n'en a pas
        # besoin (on interroge `etat()`), donc on donne l'adresse de réception
        # « à blanc » qu'Aristote expose lui-même : rien ne part vers un tiers.
        champs = {"enrichmentParameters": json.dumps(parametres),
                  "originalFileName": nom,
                  "notificationWebhookUrl": f"{self.url}/{VERSION_API}/webhook"}
        if identifiant_utilisateur:
            champs["endUserIdentifier"] = identifiant_utilisateur

        url = f"{self.url}/{VERSION_API}/enrichments/upload"
        with open(chemin, "rb") as fh:
            if HAS_TOOLBELT:
                enc = MultipartEncoder(fields={**champs, "file": (nom, fh, mime)})
                total = enc.len
                mon = MultipartEncoderMonitor(
                    enc, (lambda m: progression(m.bytes_read, total))
                    if progression else None)
                r = self.session.post(
                    url, data=mon,
                    headers={**self._entetes(), "Content-Type": mon.content_type},
                    timeout=(30, 3600))
            else:
                r = self.session.post(url, data=champs,
                                      files={"file": (nom, fh, mime)},
                                      headers=self._entetes(), timeout=(30, 3600))
        if r.status_code != 200:
            raise AristoteErreur(f"Envoi refusé ({r.status_code}) : {_message_erreur(r)}")
        d = r.json()
        if d.get("status") != "OK" or not d.get("id"):
            raise AristoteErreur(f"Réponse inattendue d'Aristote : {d}")
        return d["id"]

    # ── Suivi ───────────────────────────────────────────────────────────
    def etat(self, enrichment_id: str) -> dict:
        """Renvoie l'enrichissement : status, failureCause, initialVersionId…"""
        return self._get(f"/enrichments/{enrichment_id}").json()

    def attendre(self, enrichment_id: str,
                 rappel: Callable[[str, dict], None] | None = None,
                 intervalle: float = 15.0, delai_max: float = 6 * 3600,
                 arret: Callable[[], bool] | None = None) -> dict:
        """Interroge Aristote jusqu'à ce que la transcription existe."""
        debut = time.time()
        while True:
            d = self.etat(enrichment_id)
            statut = d.get("status", "")
            if rappel:
                rappel(statut, d)
            if statut == "FAILURE":
                raise AristoteErreur(
                    f"Aristote a échoué : {d.get('failureCause') or 'cause inconnue'}")
            if statut and statut not in ETATS_AVANT_TRANSCRIPTION:
                return d
            if time.time() - debut > delai_max:
                raise AristoteErreur("Délai d'attente dépassé.")
            fin = time.time() + intervalle
            while time.time() < fin:
                if arret and arret():
                    raise AristoteErreur("Interrompu.")
                time.sleep(0.5)

    # ── Récupération ────────────────────────────────────────────────────
    def transcription(self, enrichment_id: str,
                      version_id: str | None = None) -> dict:
        """Renvoie `transcript` : {language, text, sentences[{start,end,text,words}]}.

        Sans `version_id`, on prend la version initiale (celle de la
        transcription brute), sinon la dernière version disponible.
        """
        if not version_id:
            version_id = self.etat(enrichment_id).get("initialVersionId")
        if version_id:
            v = self._get(f"/enrichments/{enrichment_id}/versions/{version_id}").json()
        else:
            v = self._get(f"/enrichments/{enrichment_id}/versions/latest").json()
        tr = v.get("transcript")
        if not tr or not tr.get("sentences"):
            raise AristoteErreur("Cette version ne contient pas de transcription.")
        if isinstance(tr["sentences"], str):              # selon les versions
            tr["sentences"] = json.loads(tr["sentences"])
        return tr

    def supprimer(self, enrichment_id: str) -> None:
        self.session.delete(f"{self.url}/{VERSION_API}/enrichments/{enrichment_id}",
                            headers=self._entetes(), timeout=self.timeout)
