#!/usr/bin/env python3
"""
config.py — Préférences et identifiants de SousTitreur.

• Préférences (URL, langue, réglages de découpage) → ~/.soustitreur/config.json
• client_id et client_secret Aristote → coffre-fort de l'OS via keyring
  (Gestionnaire d'identification Windows / Trousseau macOS) s'ils ont été
  saisis dans les Réglages ; sinon, valeurs embarquées ci-dessous.
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402

import json
import os

DOSSIER = os.path.join(os.path.expanduser("~"), ".soustitreur")
CONFIG_PATH = os.path.join(DOSSIER, "config.json")
KEYRING_SERVICE = "SousTitreur-UToulouse"

try:
    import keyring
    HAS_KEYRING = True
except Exception:
    HAS_KEYRING = False

# ── Identifiants Aristote embarqués (facultatif) ───────────────────────────
# Remplir ces deux lignes pour que l'utilisateur n'ait RIEN à saisir au premier
# lancement. Laissées vides, l'application demande les identifiants dans les
# Réglages. Des identifiants saisis dans les Réglages restent prioritaires.
#
# ⚠️ SÉCURITÉ : un secret écrit ici est en clair dans le code, donc extractible
#    d'un exécutable et conservé dans l'historique git. Le compte de Pod permet
#    de lire et de SUPPRIMER tous les enrichissements de videos-test.
#    → Le dépôt GitHub de SousTitreur doit rester PRIVÉ.
#    → Ne diffuser les exécutables qu'à des collègues de confiance.
#    → À terme, demander à ILaaS un identifiant propre à SousTitreur.
#    → Toute rotation du secret impose de recompiler et redistribuer.
CLIENT_ID_EMBARQUE = "esup-POD"
CLIENT_SECRET_EMBARQUE = "Fa6_C9_No8"

DEFAUTS = {
    # Instance d'Aristote hébergée par ILaaS, utilisée par videos-test.utoulouse.fr.
    # L'instance publique de CentraleSupélec est https://api.aristote.education/api
    "url_aristote": "https://stt.ilaas.fr/api",
    "langue": "fr",
    "formats": ["vtt"],
    "extraire_audio": True,
    "decoupage": {},            # surcharges de sous_titres.Parametres
}


def charger() -> dict:
    os.makedirs(DOSSIER, exist_ok=True)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {**DEFAUTS, **d}


def enregistrer(cfg: dict) -> None:
    os.makedirs(DOSSIER, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def lire_identifiants() -> tuple[str, str]:
    """Identifiants du coffre-fort s'ils existent, sinon ceux embarqués."""
    if HAS_KEYRING:
        try:
            cid = keyring.get_password(KEYRING_SERVICE, "client_id") or ""
            secret = keyring.get_password(KEYRING_SERVICE, "client_secret") or ""
            if cid and secret:
                return cid, secret
        except Exception:
            pass
    return CLIENT_ID_EMBARQUE, CLIENT_SECRET_EMBARQUE


def ecrire_identifiants(client_id: str, client_secret: str) -> None:
    """Range des identifiants personnalisés dans le coffre-fort.

    Si ce sont les valeurs embarquées, on VIDE au contraire le coffre-fort :
    une copie qui y resterait masquerait le nouveau secret embarqué après une
    rotation.
    """
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if CLIENT_SECRET_EMBARQUE and             (client_id, client_secret) == (CLIENT_ID_EMBARQUE, CLIENT_SECRET_EMBARQUE):
        if HAS_KEYRING:
            for cle in ("client_id", "client_secret"):
                try:
                    keyring.delete_password(KEYRING_SERVICE, cle)
                except Exception:
                    pass
        return
    if not HAS_KEYRING:
        raise RuntimeError("Coffre-fort du système indisponible (module keyring).")
    keyring.set_password(KEYRING_SERVICE, "client_id", client_id)
    keyring.set_password(KEYRING_SERVICE, "client_secret", client_secret)
