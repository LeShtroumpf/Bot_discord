#!/bin/bash
echo check si le screen existe
if ! screen -list | grep -q "schtroumpfette"; then
  screen -S schtroumpfette
  echo screen créé
fi
echo lance le bot
docker compose up
echo bot lancé
