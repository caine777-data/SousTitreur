"""
Source UNIQUE de la version de SousTitreur.

Tous les modules l'importent d'ici. Le fichier `version.txt` (métadonnées de
l'exécutable Windows) reste à mettre à jour à la main lors d'une publication.
"""

__version__ = "0.1.2"

VERSION_TUPLE = tuple(int(x) for x in __version__.split(".")) + (0,)
