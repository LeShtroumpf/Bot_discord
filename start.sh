#!/bin/bash
echo check si le screen existe
if ! screen -list | grep -q "schtroumpfette"; then
  echo lance le bot
    docker compose up
fi
  screen -s schtroumpfette
  echo screen créé
  echo lance le bot
  docker compose up
echo bot lancé
