#!/bin/bash

# =============================================================================
# SCRIPT DE BACKUP INCREMENTAL
# =============================================================================


# -----------------------------------------------------------------------------
# Función de limpieza: se ejecuta al pulsar Ctrl+C
# Mata el proceso tar si está activo y elimina el directorio de destino parcial
# -----------------------------------------------------------------------------
cleanup() {
    echo -e "\n[!] Cancelando..."
    if [ -n "$TAR_PID" ]; then
        # Matar forzosamente el proceso de tar
        kill -9 $TAR_PID 2>/dev/null
    fi
    # Esperar a que el proceso termine
    wait 2>/dev/null
    # Eliminar el directorio de destino parcialmente creado
    rm -rf "$DEST_DIR" 2>/dev/null
    echo -e "[X] Proceso cancelado y limpieza realizada."
    exit 130
}

# Configurar el trap para capturar Ctrl+C (SIGINT)
trap cleanup SIGINT


# -----------------------------------------------------------------------------
# Validación de argumentos
# -----------------------------------------------------------------------------
# Si no se pasa ningún argumento o se pide ayuda, mostrar uso
if [ -z "$1" ] || [ "$1" == "-h" ]; then
   echo -e "[!] Uso: $0 <origen> [destino_base]"
   exit 1
fi

# Asignar el directorio de origen
SOURCE_DIR=$1


# -----------------------------------------------------------------------------
# Configurar directorio de destino
# -----------------------------------------------------------------------------
# Si no se especifica destino, usar el directorio actual
if [ -z "$2" ]; then
   BACKUP_BASE="."
   echo -e "[*] Destino --> directorio actual: $(pwd)"
else
   BACKUP_BASE="$2"
   # Verificar que el directorio destino existe (NO se crea automáticamente)
   if [ ! -d "$BACKUP_BASE" ]; then
       echo -e "[X] Directorio '$BACKUP_BASE' no existe."
       exit 1
   fi
fi


# -----------------------------------------------------------------------------
# Generar nombres de archivos y directorios
# -----------------------------------------------------------------------------
# Extraer solo el nombre del directorio de origen
DIR_NAME=$(basename "$SOURCE_DIR")
# Obtener fecha y hora actual (formato legible: dd-mm-yyyy_hh-mm-ss)
DATE=$(date +%d-%m-%Y_%H-%M-%S)
# Ruta base donde se almacenan todos los backups (busca en Iniciales e Incrementales)
BASE_PATH="$BACKUP_BASE/${DIR_NAME}_backups"


# -----------------------------------------------------------------------------
# Bloque de Comprobaciones previas
# -----------------------------------------------------------------------------
# Verificar que el directorio de origen existe
if [ ! -d "$SOURCE_DIR" ]; then
   echo -e "[X] El origen '$SOURCE_DIR' no existe."; exit 1
fi

# Verificar que existe la carpeta de backups (creada por inicial.sh)
if [ ! -d "$BASE_PATH" ]; then
   echo -e "[X] No existe una carpeta de backups para '$DIR_NAME' en '$BACKUP_BASE'."
   echo -e "[!] Ejecuta primero el script de copia COMPLETA."
   exit 1
fi


# -----------------------------------------------------------------------------
# Paso 1: BUSCAR el último archivo de metadatos (.snar)
# -----------------------------------------------------------------------------
# El archivo .snar contiene la información de todos los archivos del último backup.
# Lo necesitamos para saber qué archivos han cambiado.
# - find: busca todos los archivos .snar en la carpeta de backups
# - sort -n: ordena por fecha (más antiguo primero)
# - tail -1: toma el más reciente
LATEST_SNAPSHOT=$(find "$BASE_PATH" -name "metadatos.snar" -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -f2- -d" ")

# Verificar que se encontró algún archivo de metadatos
if [ -z "$LATEST_SNAPSHOT" ]; then
   echo -e "[X] No se encontró ningún archivo de metadatos (.snar) previo."
   exit 1
fi


# -----------------------------------------------------------------------------
# Paso 2: Configurar nueva carpeta para el backup incremental
# -----------------------------------------------------------------------------
# Estructura: base/nombre_backups/Incrementales/fecha_INC/
DEST_DIR="$BACKUP_BASE/${DIR_NAME}_backups/Incrementales/${DATE}_INC"
mkdir -p "$DEST_DIR" 2>/dev/null
FILENAME="$DEST_DIR/backup_INC.tar.gz"
# Copia del archivo de metadatos para este backup incremental
SNAPSHOT_ACTUAL="$DEST_DIR/metadatos.snar"


# -----------------------------------------------------------------------------
# Mostrar información del backup
# -----------------------------------------------------------------------------
echo -e "[*] INICIANDO COPIA INCREMENTAL"
echo -e "[*] Origen: $SOURCE_DIR"
# Mostrar en qué backup se basa (para saber qué archivos cambiaron)
echo -e "[*] Basada en: $(basename $(dirname "$LATEST_SNAPSHOT"))"
# Mostrar tamaño del directorio (no solo lo que se respaldará, sino el total)
BACKUP_SIZE=$(du -sh "$SOURCE_DIR" 2>/dev/null | cut -f1)
echo -e "[*] Tamaño a procesar: $BACKUP_SIZE"


# -----------------------------------------------------------------------------
# Paso 3: CLONAR el archivo de metadatos
# -----------------------------------------------------------------------------
# IMPORTANTE: Copiamos el archivo de metadatos anterior para:
# 1. Proteger el archivo original (no modificarlo)
# 2. Mantener la cadena de backups intacta
# 3. Crear una nueva línea temporal que tar irá actualizando
cp "$LATEST_SNAPSHOT" "$SNAPSHOT_ACTUAL"


# -----------------------------------------------------------------------------
# Paso 4: Ejecutar el backup incremental
# -----------------------------------------------------------------------------
echo -e "[~] Comprimiendo y empaquetando... (esto puede tardar)"

# Inicializar variable para almacenar el PID del proceso tar
TAR_PID=""

# -----------------------------------------------------------------------------
# Función spinner: muestra una barra de progreso animada
# -----------------------------------------------------------------------------
spinner() {
    local pid=$1
    local msg=$2
    local spin='-\|/'
    local i=0
    # Mientras el proceso esté activo, rotar el carácter
    while kill -0 $pid 2>/dev/null; do
        printf "\r[$msg] %c" "${spin:i++%4:1}"
        sleep 0.2
    done
    printf "\r[$msg] ✓\n"
}

# -----------------------------------------------------------------------------
# Ejecutar tar en segundo plano
# -----------------------------------------------------------------------------
# El flag --listed-incremental usa el archivo de metadatos copiado.
# tar compara el estado actual de los archivos con los del .snar original
# y solo empaqueta los que han cambiado, sido añadidos o eliminados.
tar -czPf "$FILENAME" \
   --listed-incremental="$SNAPSHOT_ACTUAL" \
   --no-check-device \
   "$SOURCE_DIR" &
# Guardar el PID del proceso en segundo plano
TAR_PID=$!

# Ejecutar el spinner mientras tar está corriendo
spinner $TAR_PID "Procesando"
# Esperar a que termine el proceso y capturar su código de salida
wait $TAR_PID
TAR_EXIT=$?

# -----------------------------------------------------------------------------
# Resultado
# -----------------------------------------------------------------------------
if [ $TAR_EXIT -eq 0 ]; then
   # Obtener tamaño final del archivo de backup
   FINAL_SIZE=$(du -sh "$FILENAME" 2>/dev/null | cut -f1)
   echo -e "[+] Copia incremental completada | Tamaño: $FINAL_SIZE"
else
   echo -e "[X] Error en el proceso incremental."
   # Eliminar el directorio si hubo error
   rm -rf "$DEST_DIR"
   exit 1
fi


