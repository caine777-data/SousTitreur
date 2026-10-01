#!/usr/bin/env python3
"""
editeur.py — Serveur local de l'éditeur de sous-titres.

L'éditeur est une page web (assets/editeur.html) ouverte dans le navigateur :
c'est le seul moyen simple et fiable de lire la vidéo à côté du texte. Cette
page parle à un petit serveur HTTP qui tourne DANS l'application, sur
127.0.0.1 uniquement (inaccessible depuis le réseau).

Sécurité : chaque lancement tire un jeton aléatoire. Toute requête doit le
porter, sans quoi une page web quelconque ouverte dans le navigateur pourrait
lire ou modifier les projets via localhost.

Points d'accès (tous suffixés de ?t=<jeton>) :
  GET  /p/<id>              page de l'éditeur
  GET  /api/<id>            projet (sous-titres, réglages, nom)
  POST /api/<id>            enregistre les sous-titres corrigés
  POST /api/<id>/exporter   écrit les fichiers VTT / SRT
  POST /api/<id>/redecouper refait le découpage automatique
  GET  /media/<id>          la vidéo (avec prise en charge du « Range »)
  GET  /audio/<id>          l'audio extrait (lecture de secours)
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402

import json
import mimetypes
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import projet as pj
import sous_titres as st


def _ressource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class _Serveur(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind() appelle socket.getfqdn(), une résolution DNS
        # inverse qui peut bloquer de longues secondes sous Windows. Inutile
        # pour un serveur qui n'écoute que sur 127.0.0.1.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


class ServeurEditeur:
    def __init__(self, formats_defaut: callable = lambda: ["vtt"],
                 sur_enregistrement: callable | None = None):
        self.jeton = secrets.token_urlsafe(24)
        self.formats_defaut = formats_defaut
        self.sur_enregistrement = sur_enregistrement
        self.verrou = threading.Lock()
        serveur = self

        class Gestionnaire(_Gestionnaire):
            srv = serveur

        self.httpd = _Serveur(("127.0.0.1", 0), Gestionnaire)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, pid: str) -> str:
        return f"http://127.0.0.1:{self.port}/p/{pid}?t={self.jeton}"

    def ouvrir(self, pid: str) -> None:
        webbrowser.open(self.url(pid))

    def arreter(self) -> None:
        self.httpd.shutdown()


class _Gestionnaire(BaseHTTPRequestHandler):
    srv: ServeurEditeur

    def log_message(self, *args):          # silence dans la console
        pass

    # ── Outils ──────────────────────────────────────────────────────────
    def _chemin(self) -> tuple[list[str], dict]:
        u = urllib.parse.urlparse(self.path)
        return [x for x in u.path.split("/") if x], urllib.parse.parse_qs(u.query)

    def _autorise(self, q: dict) -> bool:
        jeton = (q.get("t") or [""])[0] or self.headers.get("X-Jeton", "")
        return secrets.compare_digest(jeton, self.srv.jeton)

    def _json(self, code: int, d) -> None:
        corps = json.dumps(d, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _lire_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _projet(self, pid: str) -> dict | None:
        if not pid.isalnum() or not pj.existe(pid):
            return None
        return pj.charger(pid)

    # ── GET ─────────────────────────────────────────────────────────────
    def do_GET(self):
        parts, q = self._chemin()
        if not self._autorise(q):
            return self._json(403, {"erreur": "jeton invalide"})
        if len(parts) == 2 and parts[0] == "p":
            with open(_ressource("assets/editeur.html"), "rb") as f:
                page = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)
            return
        if len(parts) == 2 and parts[0] == "api":
            p = self._projet(parts[1])
            if p is None:
                return self._json(404, {"erreur": "projet introuvable"})
            return self._json(200, {
                "id": p["id"], "nom": p["nom"], "langue": p.get("langue"),
                "etat": p.get("etat"), "sous_titres": p["sous_titres"],
                "parametres": st.Parametres.depuis_dict(p.get("parametres")).en_dict(),
                "video": os.path.exists(p["media"]),
                "audio": bool(p.get("audio")) and os.path.exists(p["audio"]),
                "formats": self.srv.formats_defaut(),
                "version": __version__,
            })
        if len(parts) == 2 and parts[0] in ("media", "audio"):
            p = self._projet(parts[1])
            fichier = p and (p["media"] if parts[0] == "media" else p.get("audio"))
            if not fichier or not os.path.exists(fichier):
                return self._json(404, {"erreur": "fichier introuvable"})
            return self._envoyer_fichier(fichier)
        self._json(404, {"erreur": "inconnu"})

    def _envoyer_fichier(self, chemin: str) -> None:
        """Sert un fichier avec prise en charge de Range (déplacement dans la vidéo)."""
        taille = os.path.getsize(chemin)
        mime = mimetypes.guess_type(chemin)[0] or "application/octet-stream"
        debut, fin = 0, taille - 1
        plage = self.headers.get("Range")
        if plage and plage.startswith("bytes="):
            a, _, b = plage[6:].split(",")[0].partition("-")
            if a:
                debut = int(a)
                fin = int(b) if b else taille - 1
            else:
                debut = max(taille - int(b), 0)
            fin = min(fin, taille - 1)
            if debut > fin:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{taille}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {debut}-{fin}/{taille}")
        else:
            self.send_response(200)
        longueur = fin - debut + 1
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(longueur))
        self.end_headers()
        try:
            with open(chemin, "rb") as f:
                f.seek(debut)
                reste = longueur
                while reste > 0:
                    bloc = f.read(min(1024 * 1024, reste))
                    if not bloc:
                        break
                    self.wfile.write(bloc)
                    reste -= len(bloc)
        except (ConnectionError, BrokenPipeError):
            pass                         # le navigateur a interrompu (normal)

    # ── POST ────────────────────────────────────────────────────────────
    def do_POST(self):
        parts, q = self._chemin()
        if not self._autorise(q):
            return self._json(403, {"erreur": "jeton invalide"})
        if len(parts) < 2 or parts[0] != "api":
            return self._json(404, {"erreur": "inconnu"})
        with self.srv.verrou:
            p = self._projet(parts[1])
            if p is None:
                return self._json(404, {"erreur": "projet introuvable"})
            d = self._lire_json()
            action = parts[2] if len(parts) > 2 else ""
            try:
                if action == "":
                    p["sous_titres"] = [
                        {"start": float(s["start"]), "end": float(s["end"]),
                         "text": str(s["text"])} for s in d["sous_titres"]]
                    if p.get("etat") != "corrige":
                        p["etat"] = "a_corriger"
                    pj.enregistrer(p)
                    reponse = {"ok": True}
                elif action == "exporter":
                    formats = [f for f in d.get("formats", ["vtt"]) if f in ("vtt", "srt")]
                    if "sous_titres" in d:
                        p["sous_titres"] = d["sous_titres"]
                    ecrits = pj.exporter(p, formats or ["vtt"])
                    p["etat"] = "corrige"
                    pj.enregistrer(p)
                    reponse = {"ok": True, "fichiers": ecrits}
                elif action == "redecouper":
                    params = st.Parametres.depuis_dict(
                        {**(p.get("parametres") or {}), **d.get("parametres", {})})
                    pj.redecouper(p, params)
                    pj.enregistrer(p)
                    reponse = {"ok": True, "sous_titres": p["sous_titres"],
                               "parametres": params.en_dict()}
                else:
                    return self._json(404, {"erreur": "action inconnue"})
            except (KeyError, ValueError, TypeError, OSError) as e:
                return self._json(400, {"erreur": str(e)})
        if self.srv.sur_enregistrement:
            self.srv.sur_enregistrement(p["id"])
        self._json(200, reponse)
