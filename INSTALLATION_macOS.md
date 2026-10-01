# SousTitreur sur Mac

## Installer

1. Ouvrez `SousTitreur.dmg`.
2. Glissez **SousTitreur** dans **Applications**.
3. Éjectez le `.dmg`.

## Premier lancement

macOS bloque les applications qui ne viennent pas de l'App Store. Autorisez SousTitreur une seule fois :

1. Ouvrez le **Terminal** (⌘ + Espace, tapez « Terminal », Entrée).
2. Tapez ceci, avec un espace à la fin, sans valider :

   ```
   xattr -cr 
   ```

3. Glissez l'application depuis le dossier Applications dans la fenêtre du Terminal. Le chemin s'écrit tout seul.
4. Appuyez sur Entrée.
5. Lancez SousTitreur.

Si macOS affiche encore « SousTitreur est endommagé », recommencez les étapes 2 à 4 avec cette commande :

```
codesign --force --deep --sign - 
```

L'application n'est pas endommagée : ce message signale seulement une signature manquante.

## Saisir les identifiants

La fenêtre **Réglages** s'ouvre au premier lancement.

1. Laissez l'adresse de l'API : `https://stt.ilaas.fr/api`.
2. Saisissez l'identifiant client et le secret client. Cédric vous les transmet.
3. Cliquez sur **Tester la connexion**. Le message « Connexion réussie » s'affiche en vert.
4. Cliquez sur **Enregistrer**.

macOS demande l'accès au Trousseau. Cliquez sur **Toujours autoriser**.

## Sous-titrer une vidéo

1. Glissez une vidéo dans la fenêtre.
2. Attendez la mention « À corriger ». Comptez une à deux minutes pour une vidéo courte.
3. Cliquez sur **Corriger**. L'éditeur s'ouvre dans votre navigateur.
4. Relisez et corrigez. Les sous-titres hors norme portent une barre rouge.
5. Cliquez sur **Exporter les sous-titres**. Le fichier `.fr.vtt` est écrit à côté de la vidéo.

## Raccourcis de l'éditeur

| Action | Touches |
|---|---|
| Lecture, pause | Échap |
| Sous-titre précédent, suivant | ⌥ + ↑, ⌥ + ↓ |
| Reculer, avancer de 2 s | ⌥ + ←, ⌥ + → |
| Couper le sous-titre au curseur | ⌘ + Entrée |
| Enregistrer | ⌘ + S |

## Ce qu'il faut noter pendant le test

- Le temps d'attente pour chaque vidéo, avec sa durée.
- Les mots mal transcrits qui reviennent souvent.
- Les coupures de sous-titres qui vous semblent maladroites.
- Tout message d'erreur, recopié tel quel depuis le journal en bas de la fenêtre.
- Si l'éditeur lit la vidéo ou seulement le son.
