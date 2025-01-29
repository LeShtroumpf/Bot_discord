# Créer Schtroumpfette, le bot discord
***

Tout d'abord cloner le repo.

Ensuite, il va vous falloir docker et docker-compose.

Une fois que tout est installé, il faut modifier le Dockerfile avec les information necessaire.

Ensuite, il faut créer l'image de la schtroumpfette avec ```docker compose build```.

Une fois cela fait, vous pouvez lancer le bot avec ```./start.sh docker``` ou ```./start.sh screen```.

Pour lancer les tests, il faut utiliser ```python3 -m pytest``` dans le repertoire de __schtroumpfette__.