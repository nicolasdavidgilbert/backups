#!/bin/bash

show_help() {
  echo "Uso: backups < -c | --completo | -i | --incremental > <SSD>"
  echo ""
  echo "Opciones:"
  echo "  -c, --completo     Realizar backup completo"
  echo "  -i, --incremental  Realizar backup incremental"
  echo "  -h, --help         Mostrar esta ayuda"
  echo "  -v, --version      Mostrar versión"
  exit 0
}

show_version() {
  echo "backups v2.0.0"
  exit 0
}

VALID_MODE_FLAGS=("-c" "--completo" "-i" "--incremental")
VALID_INFO_FLAGS=("-h" "--help" "-v" "--version")

MODE="$1"
SSD_NAME="$2"
DATE=$(date +%F)

if [[ " ${VALID_INFO_FLAGS[*]} " =~ " ${MODE} " ]]; then
  [[ "$MODE" == "-v" || "$MODE" == "--version" ]] && show_version
  [[ "$MODE" == "-h" || "$MODE" == "--help" ]] && show_help
fi

if [ -z "$MODE" ] || [ -z "$SSD_NAME" ]; then
  show_help
fi

if [[ ! " ${VALID_MODE_FLAGS[*]} " =~ " ${MODE} " ]]; then
  echo "Modo no válido"
  exit 1
fi

if [ -z "$SUDO_COMMAND" ]; then
  echo "Permiso denegado"
  exit 1
fi

if [ "$MODE" == "-c" ]; then
  MODE="--completo"
elif [ "$MODE" == "-i" ]; then
  MODE="--incremental"
fi

SOURCE="/media/${SUDO_USER:-$USER}/$SSD_NAME"
BASE="/backups/$SSD_NAME"

mkdir -p "$BASE/completo"
mkdir -p "$BASE/incrementales"

format_size() {
  numfmt --to=iec-i --suffix=B "$1" 2>/dev/null || echo "$1 bytes"
}

ask_continue() {
  read -p "  ▶ Continuar? [S/n] " -n 1 -r
  echo ""
  [[ ! $REPLY =~ ^[Nn]$ ]] && return 0
  return 1
}

if [ "$MODE" == "--completo" ]; then
  DEST="$BASE/completo/$DATE"

  echo "Backup COMPLETO - Analizando..."

  COUNT=$(find "$SOURCE" -type f 2>/dev/null | wc -l)
  SIZE=$(du -sb "$SOURCE" 2>/dev/null | awk '{print $1}')
  echo ""
  echo " · Archivos:   $COUNT"
  echo " · Tamaño:     $(format_size ${SIZE:-0})"
  echo ""
  
  if ! ask_continue; then
    echo ""
    echo "Cancelado"
    trap - SIGINT SIGTERM SIGHUP
    exit 0
  fi
  
  echo "  ▶ Iniciando..."
  echo ""
  rsync -a --delete --info=progress2 "$SOURCE/" "$DEST/"

elif [ "$MODE" == "--incremental" ]; then
  LAST=$(ls -td "$BASE/completo/"* "$BASE/incrementales/"* 2>/dev/null | head -1)

  DEST="$BASE/incrementales/$DATE"

  if [ -z "$LAST" ]; then
    echo "No hay incremental previo. Haz primero uno completo."
    trap - SIGINT SIGTERM SIGHUP
    exit 1
  fi

  echo "   Backup INCREMENTAL - Analizando..."

  echo "  Referencia: $(basename "$LAST")"
  STATS=$(rsync -ai --delete --link-dest="$LAST" "$SOURCE/" "$DEST/" 2>&1)
  COUNT=$(echo "$STATS" | grep -c "^[<>ch]")
  SIZE=$(echo "$STATS" | awk '/total size is/ {gsub(/[,.]/,"",$5); print $5}')
  echo ""
  echo " · Archivos:   $COUNT"
  echo " · Tamaño:     $(format_size ${SIZE:-0})"
  echo ""
  
  if ! ask_continue; then
    echo "Cancelado"
    exit 0
  fi
  
  echo "  ▶ Iniciando..."
  echo ""
  rsync -a --delete --info=progress2 \
  --link-dest="$LAST" \
  "$SOURCE/" "$DEST/"

else
  echo "Modo no válido"
  exit 1
fi
