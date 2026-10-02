# SousTitreur

Sous-titres aux normes à partir d'Aristote, avec relecture avant export.

Université de Toulouse, MFCA. Version 0.1.2.

## Le problème réglé

Pod reçoit d'Aristote des phrases entières et les affiche telles quelles. Un sous-titre peut alors compter 400 caractères et couvrir la moitié de l'image pendant 30 secondes.

SousTitreur interroge Aristote directement, sans passer par Pod. Il récupère l'horodatage mot par mot et redécoupe le texte :

- 42 caractères au plus par ligne ;
- 2 lignes au plus par sous-titre ;
- entre 1 et 6 secondes à l'écran ;
- 20 caractères par seconde au plus ;
- coupures en fin de phrase, sur une virgule ou sur une pause, jamais après « le », « de », « et », ni entre un prénom et un nom.

Ces valeurs se changent dans **Réglages**.

## Lancer l'application

Installez les dépendances une seule fois :

```bash
pip install -r requirements.txt
```

Puis lancez :

```bash
python app.py
```

Au premier lancement, ouvrez **Réglages** et saisissez :

- l'adresse de l'API : `https://stt.ilaas.fr/api` ;
- l'identifiant client et le secret client (ceux du serveur Pod).

Cliquez sur **Tester la connexion**. Le secret est rangé dans le Gestionnaire d'identification de Windows ou le Trousseau de macOS, jamais dans un fichier.

Sur Mac, suivez `INSTALLATION_macOS.md`.

## Sous-titrer une vidéo

1. Déposez la vidéo dans la fenêtre. SousTitreur en extrait le son et l'envoie à Aristote. Une heure de cours pèse environ 22 Mo.
2. Attendez la ligne « À corriger ». Comptez une minute pour une vidéo courte. Vous pouvez fermer l'application : le suivi reprend au prochain lancement.
3. Cliquez sur **Corriger**. L'éditeur s'ouvre dans votre navigateur.
4. Relisez. Les sous-titres hors norme portent une barre rouge.
5. Cliquez sur **Exporter les sous-titres**. Le fichier `.fr.vtt` est écrit à côté de la vidéo.
6. Déposez ce fichier dans Pod, onglet Sous-titres de la vidéo.

## Corriger des sous-titres déjà produits par Pod

Deux moyens, sans renvoyer la vidéo :

- Déposez le fichier VTT ou SRT téléchargé depuis Pod. Il est redécoupé aux normes. Placez la vidéo du même nom dans le même dossier pour l'avoir dans l'éditeur.
- Cliquez sur **Reprendre un ID Aristote** et collez l'identifiant de l'enrichissement. Le découpage est alors plus précis, car il s'appuie sur l'horodatage mot par mot.

Un fichier existant n'est jamais écrasé : l'export prend le suffixe « (corrigé) ».

## L'éditeur

| Action | Windows | macOS |
|---|---|---|
| Lecture, pause | Échap | Échap |
| Sous-titre précédent, suivant | Alt + ↑, Alt + ↓ | ⌥ + ↑, ⌥ + ↓ |
| Reculer, avancer de 2 s | Alt + ←, Alt + → | ⌥ + ←, ⌥ + → |
| Couper le sous-titre au curseur | Ctrl + Entrée | ⌘ + Entrée |
| Enregistrer | Ctrl + S | ⌘ + S |

Chaque sous-titre offre aussi : caler le début ou la fin sur la position de lecture, rééquilibrer les deux lignes, fusionner avec le suivant, supprimer.

**Rechercher et remplacer** corrige d'un coup un nom propre mal transcrit dans toute la vidéo.

Les corrections sont enregistrées automatiquement.

## Les fichiers

| Fichier | Rôle | Réutilisable dans PodAdmin |
|---|---|---|
| `aristote_api.py` | Client de l'API Aristote | oui |
| `sous_titres.py` | Découpage aux normes, export VTT et SRT | oui |
| `projet.py` | Stockage des projets | oui |
| `editeur.py` + `assets/editeur.html` | Éditeur de correction | oui |
| `media.py` | Extraction du son avec ffmpeg | oui |
| `config.py` | Préférences et coffre-fort | à fusionner avec celui de PodAdmin |
| `app.py` | Fenêtre principale | non |

Les projets et le son extrait sont rangés dans `~/.soustitreur`.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Compilation

Le fichier `.github/workflows/build.yml` produit trois fichiers : `SousTitreur-Setup.exe` (installeur Windows), `SousTitreur.exe` (version portable) et `SousTitreur.dmg` (macOS). Lancez-le depuis l'onglet Actions du dépôt GitHub, bouton **Run workflow**.

À chaque publication, le numéro de version se change dans `__version__.py` et dans `version.txt`.
