#!/bin/zsh
# auto_refresh.sh — corre refresh_daily + git push de forma automática
# Llamado por launchd cada mañana

REPO="/Users/germanmucino/Desktop/Descargas firefox/INEGI interactivo/Interactivo indicadores INEGI/indicadores_inegi"
LOG="$REPO/logs/auto_refresh.log"
ENV_FILE="$HOME/.panorama_env"

mkdir -p "$REPO/logs"

echo "==============================" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') — inicio" >> "$LOG"

# Cargar token desde archivo de entorno
if [ -f "$ENV_FILE" ]; then
  source "$ENV_FILE"
else
  echo "ERROR: no existe $ENV_FILE" >> "$LOG"
  exit 1
fi

if [ -z "$INEGI_BIE_TOKEN" ]; then
  echo "ERROR: INEGI_BIE_TOKEN vacío" >> "$LOG"
  exit 1
fi

cd "$REPO" || exit 1

# Refresh: ingest + build
/usr/bin/python3 scripts/refresh_daily.py >> "$LOG" 2>&1
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo "ERROR: refresh_daily.py falló (exit $STATUS)" >> "$LOG"
  exit 1
fi

# Git push
git add -A >> "$LOG" 2>&1
git commit -m "Data: actualización automática $(date '+%Y-%m-%d')" >> "$LOG" 2>&1
git push >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') — OK" >> "$LOG"
