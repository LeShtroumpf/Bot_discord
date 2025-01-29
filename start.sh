#!/bin/bash

case $1 in
  "docker")	docker compose up -d;;
  "screen") screen -dmS schtroumpfette docker compose up;;
  *) echo "Les seuls params autorisé sont docker|screen";;
esac
