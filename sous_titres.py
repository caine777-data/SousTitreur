#!/usr/bin/env python3
"""
sous_titres.py — Découpage d'une transcription en sous-titres conformes.

Module SANS interface graphique ni accès réseau : il peut être importé tel quel
par une autre application (PodAdmin, par exemple).

Entrée : la transcription renvoyée par Aristote (liste de phrases, chacune avec
ses mots horodatés). Sortie : une liste de sous-titres (début, fin, texte sur
une ou deux lignes), puis un fichier WebVTT ou SRT.

Normes appliquées par défaut (réglables, voir `Parametres`) :
  • 42 caractères au plus par ligne, 2 lignes au plus par sous-titre ;
  • durée d'affichage entre 1 s et 6 s ;
  • vitesse de lecture visée : 17 caractères par seconde, 20 au maximum ;
  • 80 ms d'écart minimum entre deux sous-titres (2 images à 25 i/s) ;
  • pas de coupure après un article, une préposition ou une conjonction ;
  • coupure de préférence en fin de phrase, puis sur une virgule, puis sur
    une pause de la voix.

Le découpage est calculé par programmation dynamique : parmi toutes les façons
de grouper les mots en sous-titres, on retient celle dont le « coût » total est
le plus faible (coupures mal placées, sous-titres trop courts, lecture trop
rapide, lignes déséquilibrées).
"""

from __future__ import annotations

__author__ = "Cédric MONNA"
from __version__ import __version__   # noqa: E402  (source unique)

import re
from dataclasses import dataclass, field, asdict

# ─────────────────────────────── Réglages ────────────────────────────────


@dataclass
class Parametres:
    car_par_ligne: int = 42          # CPL
    lignes_max: int = 2
    duree_min: float = 1.0           # secondes
    duree_max: float = 6.0
    cps_cible: float = 17.0          # caractères par seconde visés
    cps_max: float = 20.0            # au-delà : lecture trop rapide
    ecart_min: float = 0.08          # entre deux sous-titres
    enchainement: float = 0.5        # écart < à ce seuil : on colle les sous-titres
    pause_forte: float = 1.5         # silence qui impose une coupure
    filtrer_hallucinations: bool = True

    @classmethod
    def depuis_dict(cls, d: dict | None) -> "Parametres":
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k):
                setattr(p, k, type(getattr(p, k))(v))
        return p

    def en_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────── Modèle ──────────────────────────────────


@dataclass
class Mot:
    texte: str
    debut: float
    fin: float


@dataclass
class SousTitre:
    debut: float
    fin: float
    texte: str                       # lignes séparées par « \n »

    def en_dict(self) -> dict:
        return {"start": round(self.debut, 3), "end": round(self.fin, 3),
                "text": self.texte}

    @classmethod
    def depuis_dict(cls, d: dict) -> "SousTitre":
        return cls(float(d["start"]), float(d["end"]), str(d["text"]))


@dataclass
class Alerte:
    code: str
    message: str


# Mots après lesquels on évite de couper (une ligne ou un sous-titre ne doit
# pas se terminer sur « le », « de », « et »…). Liste française et anglaise.
MOTS_FAIBLES = {
    # articles et déterminants
    "le", "la", "les", "l'", "un", "une", "des", "du", "de", "d'", "au", "aux",
    "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes", "son",
    "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs", "quel",
    "quelle", "quels", "quelles", "chaque", "plusieurs", "certains",
    # prépositions
    "à", "en", "dans", "par", "pour", "sur", "sous", "avec", "sans", "chez",
    "vers", "entre", "contre", "depuis", "pendant", "selon", "après", "avant",
    "jusqu'", "jusqu'à",
    # conjonctions, pronoms relatifs, pronoms clitiques
    "et", "ou", "mais", "donc", "or", "ni", "car", "que", "qu'", "qui", "dont",
    "où", "si", "comme", "quand", "lorsque", "puisque", "parce",
    "je", "j'", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "ne", "n'", "se", "s'", "me", "m'", "te", "t'", "y",
    # auxiliaires courants
    "est", "sont", "a", "ont", "c'est",
    # anglais
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "and", "or",
    "but", "that", "which", "who", "is", "are", "was", "were", "i", "you",
    "he", "she", "we", "they", "it", "my", "your", "his", "her", "our", "their",
}

FIN_PHRASE = (".", "?", "!", "…", "»")
PONCT_FAIBLE = (",", ";", ":")

# Phrases que Whisper invente sur les silences ou la musique.
HALLUCINATIONS = [
    r"^sous-titr(age|es|é)",
    r"amara\.org",
    r"^merci d'avoir regardé",
    r"^merci de votre attention\.?$",
    r"^\W*$",
]
_RE_HALLU = [re.compile(p, re.IGNORECASE) for p in HALLUCINATIONS]


def _est_faible(mot: str) -> bool:
    m = mot.lower().strip("«»\"“”()[]")
    return m in MOTS_FAIBLES or m.endswith("'") or m.endswith("’")


def _fin_phrase(mot: str) -> bool:
    return mot.rstrip("»\"”)  ").endswith((".", "?", "!", "…"))


def _fin_ponct(mot: str) -> bool:
    return mot.endswith(PONCT_FAIBLE)


def _nom_compose(mot: str, suivant: str) -> bool:
    """« George Doran », « Paul Sabatier » : deux majuscules à ne pas séparer."""
    return (mot[:1].isupper() and suivant[:1].isupper()
            and not _fin_phrase(mot) and not _fin_ponct(mot))


# ──────────────────────── Lecture de la transcription ──────────────────────


def _nombre(v, defaut: float | None = None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def _repartir(texte: str, debut: float, fin: float) -> list[Mot]:
    """Mots d'une phrase sans horodatage : durée répartie selon leur longueur."""
    morceaux = texte.split()
    if not morceaux:
        return []
    total = sum(len(m) + 1 for m in morceaux)
    duree = max(fin - debut, 0.0)
    mots, t = [], debut
    for m in morceaux:
        d = duree * (len(m) + 1) / total
        mots.append(Mot(m, t, t + d))
        t += d
    return mots


def _fusionner(mots: list[Mot]) -> list[Mot]:
    """Nettoie les mots bruts de Whisper.

    Whisper renvoie parfois la ponctuation comme un mot à part (« ? »), ou
    découpe les élisions (« l' » + « école ») et les traits d'union
    (« a » + « -t-il »). On recolle ces morceaux au mot précédent pour qu'une
    coupure ne tombe jamais au milieu.
    """
    sortie: list[Mot] = []
    for m in mots:
        t = m.texte.strip()
        if not t:
            continue
        if sortie:
            prec = sortie[-1]
            if re.fullmatch(r"[?!:;»)\]]+", t):
                prec.texte += " " + t          # espace insécable
                prec.fin = max(prec.fin, m.fin)
                continue
            # « d » + « 'identité », « l' » + « école », « a » + « -t-il »
            if re.fullmatch(r"[.,…]+", t) or t.startswith(("-", "'", "’")) \
                    or prec.texte.endswith(("'", "’", "« ", "(")):
                prec.texte += t
                prec.fin = max(prec.fin, m.fin)
                continue
        sortie.append(Mot(t, m.debut, m.fin))
    return sortie


def mots_depuis_aristote(phrases: list[dict],
                         filtrer_hallucinations: bool = True) -> list[Mot]:
    """Transforme `transcript.sentences` d'Aristote en liste de mots horodatés.

    Chaque phrase peut porter une clé `words` (horodatage mot par mot, cas
    normal avec faster-whisper) ; à défaut, on répartit la durée de la phrase.
    """
    mots: list[Mot] = []
    for ph in phrases or []:
        texte = str(ph.get("text") or "").strip()
        if filtrer_hallucinations and any(r.search(texte) for r in _RE_HALLU):
            continue
        debut = _nombre(ph.get("start"), 0.0)
        fin = _nombre(ph.get("end"), debut)
        bruts = []
        for w in ph.get("words") or []:
            wt = str(w.get("text", w.get("word", "")))
            bruts.append(Mot(wt, _nombre(w.get("start")), _nombre(w.get("end"))))
        if bruts and any(b.texte.strip() for b in bruts):
            # Complète les horodatages manquants par interpolation.
            for i, b in enumerate(bruts):
                if b.debut is None:
                    b.debut = bruts[i - 1].fin if i else debut
                if b.fin is None:
                    b.fin = b.debut
            mots.extend(bruts)
        else:
            mots.extend(_repartir(texte, debut, fin))
    mots = _fusionner(mots)
    # Horodatages croissants (Whisper se contredit parfois de quelques ms).
    for i in range(1, len(mots)):
        if mots[i].debut < mots[i - 1].debut:
            mots[i].debut = mots[i - 1].debut
        if mots[i].fin < mots[i].debut:
            mots[i].fin = mots[i].debut
    return mots


# ───────────────────────────── Découpage en lignes ──────────────────────────


def _cout_coupure_ligne(mot: str, suivant: str = "") -> float:
    if suivant and _nom_compose(mot, suivant):
        return 4.0
    if _fin_phrase(mot):
        return -1.0
    if _fin_ponct(mot):
        return -0.6
    if _est_faible(mot):
        return 3.0
    return 0.0


def couper_lignes(mots: list[str], p: Parametres) -> tuple[list[str], float] | None:
    """Répartit des mots sur `p.lignes_max` lignes au plus.

    Renvoie (lignes, coût) ou None si c'est impossible sans dépasser
    `p.car_par_ligne`. Préférence : peu de lignes, coupure sur la ponctuation,
    lignes équilibrées, jamais de ligne finissant par un mot faible.
    """
    n = len(mots)
    if n == 0:
        return [""], 0.0
    texte = " ".join(mots)
    if len(texte) <= p.car_par_ligne:
        return [texte], 0.0
    if n == 1:
        return None

    # meilleur[k][i] : coût minimal pour placer mots[:i] sur k lignes.
    INF = float("inf")
    meilleur = [[INF] * (n + 1) for _ in range(p.lignes_max + 1)]
    retour = [[-1] * (n + 1) for _ in range(p.lignes_max + 1)]
    meilleur[0][0] = 0.0
    for k in range(1, p.lignes_max + 1):
        for i in range(1, n + 1):
            longueur = -1
            for j in range(i - 1, -1, -1):
                longueur += len(mots[j]) + 1
                if longueur > p.car_par_ligne:
                    break
                if meilleur[k - 1][j] == INF:
                    continue
                c = meilleur[k - 1][j]
                if i < n:
                    c += _cout_coupure_ligne(mots[i - 1], mots[i])
                if c < meilleur[k][i]:
                    meilleur[k][i], retour[k][i] = c, j
    choix = None
    for k in range(1, p.lignes_max + 1):
        if meilleur[k][n] == INF:
            continue
        # Reconstitue les lignes pour mesurer leur équilibre.
        bornes, i = [], n
        for kk in range(k, 0, -1):
            j = retour[kk][i]
            bornes.append((j, i))
            i = j
        lignes = [" ".join(mots[a:b]) for a, b in reversed(bornes)]
        lg = [len(x) for x in lignes]
        desequilibre = (max(lg) - min(lg)) / p.car_par_ligne
        # Légère préférence pour la « pyramide » : ligne du bas plus longue.
        haut_lourd = 0.3 if k == 2 and lg[0] > lg[1] + 8 else 0.0
        cout = meilleur[k][n] + 2.0 * desequilibre + haut_lourd + 0.5 * (k - 1)
        if choix is None or cout < choix[1]:
            choix = (lignes, cout)
    return choix


# ─────────────────────────── Découpage en sous-titres ───────────────────────


def _cout_sous_titre(mots: list[Mot], a: int, b: int, n: int,
                     p: Parametres) -> tuple[float, list[str]] | None:
    """Coût d'un sous-titre formé des mots[a:b], ou None s'il est impossible."""
    textes = [m.texte for m in mots[a:b]]
    res = couper_lignes(textes, p)
    if res is None:
        return None
    lignes, cout_lignes = res
    duree = mots[b - 1].fin - mots[a].debut
    if duree > p.duree_max and b - a > 1:
        return None

    cout = 2.0 + cout_lignes                  # coût fixe : évite l'émiettement
    dernier = mots[b - 1].texte
    # Bout de phrase orphelin (« du dispositif. » seul à l'écran) : on préfère
    # rééquilibrer avec le sous-titre précédent.
    if a > 0 and not _fin_phrase(mots[a - 1].texte) \
            and sum(len(x) for x in lignes) < 20:
        cout += 3.0
    if b < n:                                 # nature de la coupure finale
        pause = mots[b].debut - mots[b - 1].fin
        if _fin_phrase(dernier):
            cout += 0.0
        elif _fin_ponct(dernier):
            cout += 1.0
        elif pause >= 0.4:
            cout += 1.5
        else:
            cout += 4.0
        if _est_faible(dernier):
            cout += 8.0
        if _nom_compose(dernier, mots[b].texte):
            cout += 8.0
    # Plusieurs phrases dans un même sous-titre : toléré si elles sont courtes.
    for k in range(a, b - 1):
        if _fin_phrase(mots[k].texte):
            cout += 2.5
    # Trop court à l'écran.
    if duree < p.duree_min:
        cout += 3.0 * (p.duree_min - duree)
    # Lecture trop rapide (sur la durée réelle de parole).
    nb_car = sum(len(x) for x in lignes)
    cps = nb_car / max(duree, 0.3)
    if cps > p.cps_max:
        cout += 0.4 * (cps - p.cps_max)
    return cout, lignes


def decouper(mots: list[Mot], p: Parametres | None = None) -> list[SousTitre]:
    """Groupe les mots en sous-titres, puis ajuste les horaires."""
    p = p or Parametres()
    n = len(mots)
    if n == 0:
        return []
    INF = float("inf")
    meilleur = [INF] * (n + 1)
    retour: list[tuple[int, list[str]] | None] = [None] * (n + 1)
    meilleur[0] = 0.0
    limite_car = p.car_par_ligne * p.lignes_max + p.lignes_max
    for b in range(1, n + 1):
        car = -1
        for a in range(b - 1, -1, -1):
            car += len(mots[a].texte) + 1
            if car > limite_car and b - a > 1:
                break
            # Un long silence à l'intérieur impose une coupure.
            if a < b - 1 and mots[a + 1].debut - mots[a].fin >= p.pause_forte:
                break
            if meilleur[a] == INF:
                continue
            res = _cout_sous_titre(mots, a, b, n, p)
            if res is None:
                if b - a == 1:              # mot isolé trop long : on l'accepte
                    res = (50.0, [mots[a].texte])
                else:
                    continue
            c = meilleur[a] + res[0]
            if c < meilleur[b]:
                meilleur[b] = c
                retour[b] = (a, res[1])

    blocs = []
    b = n
    while b > 0:
        a, lignes = retour[b]
        blocs.append(SousTitre(mots[a].debut, mots[b - 1].fin, "\n".join(lignes)))
        b = a
    blocs.reverse()
    return ajuster_horaires(blocs, p)


def ajuster_horaires(sts: list[SousTitre], p: Parametres) -> list[SousTitre]:
    """Allonge les sous-titres trop brefs et règle les écarts entre eux.

    • durée au moins `duree_min` et assez longue pour lire à `cps_cible` ;
    • jamais au-delà du début du suivant moins `ecart_min` ;
    • si l'écart restant est inférieur à `enchainement`, on colle les deux
      sous-titres (écart = `ecart_min`) pour éviter un clignotement.
    """
    for i, st in enumerate(sts):
        nb_car = len(st.texte.replace("\n", ""))
        voulu = max(st.fin, st.debut + p.duree_min,
                    st.debut + nb_car / p.cps_cible)
        voulu = min(voulu, st.debut + max(p.duree_max, st.fin - st.debut))
        if i + 1 < len(sts):
            limite = sts[i + 1].debut - p.ecart_min
            if limite - voulu < p.enchainement - p.ecart_min:
                voulu = limite
            voulu = min(voulu, limite)
        st.fin = max(voulu, st.debut + 0.2)
    return sts


# ────────────────────────────── Contrôle ─────────────────────────────────


def verifier(st: SousTitre, p: Parametres) -> list[Alerte]:
    """Alertes affichées dans l'éditeur pour un sous-titre corrigé à la main."""
    alertes = []
    lignes = st.texte.split("\n")
    if len(lignes) > p.lignes_max:
        alertes.append(Alerte("lignes", f"{len(lignes)} lignes (max {p.lignes_max})"))
    for i, l in enumerate(lignes, 1):
        if len(l) > p.car_par_ligne:
            alertes.append(Alerte("cpl", f"ligne {i} : {len(l)} car. (max {p.car_par_ligne})"))
    duree = st.fin - st.debut
    if duree < p.duree_min - 1e-6:
        alertes.append(Alerte("court", f"{duree:.1f} s (min {p.duree_min:g} s)"))
    if duree > p.duree_max + 1e-6:
        alertes.append(Alerte("long", f"{duree:.1f} s (max {p.duree_max:g} s)"))
    nb = len(st.texte.replace("\n", ""))
    if duree > 0 and nb / duree > p.cps_max:
        alertes.append(Alerte("cps", f"{nb / duree:.0f} car./s (max {p.cps_max:g})"))
    return alertes


# ─────────────────────────────── Export ──────────────────────────────────


def _horodatage(t: float, sep: str) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def vers_vtt(sts: list[SousTitre]) -> str:
    blocs = ["WEBVTT\n"]
    for i, st in enumerate(sts, 1):
        blocs.append(f"{i}\n{_horodatage(st.debut, '.')} --> "
                     f"{_horodatage(st.fin, '.')}\n{st.texte.strip()}\n")
    return "\n".join(blocs)


def vers_srt(sts: list[SousTitre]) -> str:
    blocs = []
    for i, st in enumerate(sts, 1):
        blocs.append(f"{i}\n{_horodatage(st.debut, ',')} --> "
                     f"{_horodatage(st.fin, ',')}\n{st.texte.strip()}\n")
    return "\n".join(blocs)


def lire_horodatage(t: str) -> float:
    t = t.strip().replace(",", ".")
    parties = t.split(":")
    s = float(parties[-1])
    if len(parties) >= 2:
        s += int(parties[-2]) * 60
    if len(parties) >= 3:
        s += int(parties[-3]) * 3600
    return s


def lire_vtt_srt(contenu: str) -> list[SousTitre]:
    """Relit un fichier VTT ou SRT (pour corriger des sous-titres existants)."""
    sts = []
    for bloc in re.split(r"\n\s*\n", contenu.replace("\r", "")):
        lignes = [l for l in bloc.split("\n") if l.strip()]
        for i, l in enumerate(lignes):
            if "-->" in l:
                a, b = l.split("-->")
                texte = "\n".join(lignes[i + 1:])
                sts.append(SousTitre(lire_horodatage(a),
                                     lire_horodatage(b.split()[0]), texte))
                break
    return sts
