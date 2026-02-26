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
  echo "backups v1.0.0"
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

if [ "$MODE" == "--completo" ]; then
  DEST="$BASE/completo/$DATE"
  rsync -a --delete --info=progress2 "$SOURCE/" "$DEST/"

elif [ "$MODE" == "--incremental" ]; then
  LAST=$(ls -d "$BASE/incrementales/"* 2>/dev/null | sort | tail -n 1)

  DEST="$BASE/incrementales/$DATE"

  if [ -z "$LAST" ]; then
    echo "No hay incremental previo. Haz primero uno completo."
    exit 1
  fi

  rsync -a --delete --info=progress2 \
  --link-dest="$LAST" \
  "$SOURCE/" "$DEST/"

else
  echo "Modo no válido"
  exit 1
fi
