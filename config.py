#!/usr/bin/env python3
"""
config.py — Préférences et identifiants de SousTitreur.

• Préférences (URL, langue, réglages de découpage) → ~/.soustitreur/config.json
• client_id et client_secret Aristote → coffre-fort de l'OS via keyring
  (Gestionnaire d'identification Windows / Trousseau macOS). Jamais en clair.
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
    if not HAS_KEYRING:
        return "", ""
    try:
        return (keyring.get_password(KEYRING_SERVICE, "client_id") or "",
                keyring.get_password(KEYRING_SERVICE, "client_secret") or "")
    except Exception:
        return "", ""


def ecrire_identifiants(client_id: str, client_secret: str) -> None:
    if not HAS_KEYRING:
        raise RuntimeError("Coffre-fort du système indisponible (module keyring).")
    keyring.set_password(KEYRING_SERVICE, "client_id", client_id.strip())
    keyring.set_password(KEYRING_SERVICE, "client_secret", client_secret.strip())
