#!/usr/bin/env python3
"""
media.py — Extraction de la piste audio avant l'envoi à Aristote.

Aristote n'a besoin que du son. Envoyer un MP3 mono de 48 kbit/s au lieu de la
vidéo divise la taille par 20 à 50 : une heure de cours pèse environ 22 Mo au
lieu de 1 à 2 Go. L'envoi est plus rapide et ne risque plus d'être coupé.

ffmpeg est fourni par le paquet imageio-ffmpeg (embarqué dans l'exécutable).
S'il est absent, on envoie la vidéo telle quelle.
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402

import os
import re
import shutil
import subprocess
import sys


def ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        # Dans l'exécutable macOS, le binaire embarqué peut perdre son droit
        # d'exécution lors de la décompression.
        if sys.platform != "win32" and not os.access(exe, os.X_OK):
            os.chmod(exe, 0o755)
        return exe
    except Exception:
        return shutil.which("ffmpeg")


def _sans_console() -> dict:
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}      # CREATE_NO_WINDOW
    return {}


def extraire_audio(video: str, sortie: str, progression=None) -> bool:
    """Crée `sortie` (MP3 mono 16 kHz). Renvoie False si ffmpeg est absent."""
    exe = ffmpeg()
    if not exe:
        return False
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    cmd = [exe, "-y", "-hide_banner", "-i", video, "-vn", "-ac", "1",
           "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", sortie]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace",
                            **_sans_console())
    duree = None
    for ligne in proc.stderr:
        if duree is None:
            m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", ligne)
            if m:
                duree = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        m = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", ligne)
        if m and duree and progression:
            t = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
            progression(min(t / duree, 1.0))
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(sortie):
        raise RuntimeError("ffmpeg n'a pas pu extraire le son. "
                           "Vérifiez que la vidéo contient une piste audio.")
    return True
