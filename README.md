# Créer Schtroumpfette, le bot discord
***

Tout d'abord cloner le repo.

Ensuite, il va vous falloir docker et docker-compose.

Une fois que tout est installé, il faut insérer votre TOKEN dans le Dockerfile.

Ensuite, il faut créer l'image de la schtroumpfette avec ```docker build -t schtroumpfette .```.

Une fois cela fait, vous pouvez lancer le bot avec ```./start.sh```.