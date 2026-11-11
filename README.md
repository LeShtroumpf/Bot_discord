# Créer Schtroumpfette, le bot discord
***

Tout d'abord cloner le repo.

Ensuite, il va vous falloir docker et docker-compose.

Une fois que tout est installé, il faut modifier le Dockerfile avec les information necessaire.

Ensuite, il faut créer l'image de la schtroumpfette avec ```docker compose build```.

Une fois cela fait, vous pouvez lancer le bot avec ```./start.sh docker``` ou ```./start.sh screen```.

Pour lancer les tests, il faut utiliser ```python3 -m pytest``` dans le repertoire de __schtroumpfette__.
## Déploiement (CI/CD)

Le workflow `.github/workflows/ci.yml` (GitHub Actions) :

- **PR vers `master`** : job `Tests` (flake8 sur les `.py` modifiés + pytest). C'est un check obligatoire pour merger.
- **Merge sur `master`** : `Tests`, puis `Build` (image `ghcr.io/leshtroumpf/bot_discord:<sha du commit>`), puis `Deploy` (SSH : `docker compose -f docker-compose.prod.yml pull` + `up -d`, vérification que le bot tourne, nettoyage des vieilles images).
- **Lancement manuel** (onglet Actions → CI/CD → Run workflow) : redéploie le commit courant, ou, avec l'entrée `sha`, une image déjà publiée (retour arrière).

Au démarrage, le bot annonce sa version dans le salon de logs (« 🚀 Schtroumpfette démarrée sur `<sha>` »).

Sur le serveur, seuls `.env`, `schtroumpfette/settings.json` et `schtroumpfette/warframe/cache/` sont propres à l'installation : le code vient de l'image. `settings.json` est copié en `settings.json.bak` avant chaque redémarrage.

Secrets de l'environnement GitHub `production` : `SSH_PRIVATE_KEY`, `TARGET_HOST`, `TARGET_USER`, `TARGET_DIR` (dossier du bot sur le serveur), `GHCR_PAT` (token `read:packages` pour télécharger l'image privée).

En local, `docker-compose.yml` reste utilisé pour le développement (build + code monté).
