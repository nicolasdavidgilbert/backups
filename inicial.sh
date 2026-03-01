#!/bin/bash

# =============================================================================
# SCRIPT DE BACKUP COMPLETO (INICIAL)
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
   echo -e "[*] Destino: directorio actual"
else
   BACKUP_BASE="$2"
   # Crear el directorio destino si no existe
   if [ ! -d "$BACKUP_BASE" ]; then
       echo -e "[~] Creando directorio destino..."
       mkdir -p "$BACKUP_BASE" 2>/dev/null
       if [ $? -ne 0 ]; then
           echo -e "[X] No se pudo crear el destino (revisa permisos)."
           exit 1
       fi
   fi
fi


# -----------------------------------------------------------------------------
# Generar nombres de archivos y directorios
# -----------------------------------------------------------------------------
# Extraer solo el nombre del directorio de origen (sin la ruta)
DIR_NAME=$(basename "$SOURCE_DIR")
# Obtener fecha y hora actual para nombrar la carpeta (formato legible: dd-mm-yyyy_hh-mm-ss)
DATE=$(date +%d-%m-%Y_%H-%M-%S)

# Estructura de directorios: destino/nombre_backups/Iniciales/fecha_FULL/
DEST_DIR="$BACKUP_BASE/${DIR_NAME}_backups/Iniciales/${DATE}_FULL"
FILENAME="$DEST_DIR/backup_FULL.tar.gz"
# Archivo .snar: contiene los metadatos para backups incrementales futuros
SNAPSHOT_FILE="$DEST_DIR/metadatos.snar"


# -----------------------------------------------------------------------------
# Bloque de Comprobaciones previas
# -----------------------------------------------------------------------------
# Verificar que el directorio de origen existe
if [ ! -d "$SOURCE_DIR" ]; then
   echo -e "[X] El origen '$SOURCE_DIR' no existe."; exit 1
fi
# Verificar que tenemos permisos de lectura en el origen
if [ ! -r "$SOURCE_DIR" ]; then
   echo -e "[X] Sin permisos de lectura en origen."; exit 1
fi


# -----------------------------------------------------------------------------
# Crear estructura de directorios
# -----------------------------------------------------------------------------
# Crear la carpeta específica del backup
mkdir -p "$DEST_DIR" 2>/dev/null
# Verificar permisos de escritura en el destino
if [ ! -w "$DEST_DIR" ]; then
   echo -e "[X] No se puede escribir en el destino '$DEST_DIR'."; exit 1
fi


# -----------------------------------------------------------------------------
# Ejecución del backup completo
# -----------------------------------------------------------------------------
echo -e "[*] INICIANDO COPIA COMPLETA"
echo -e "[*] Origen: $SOURCE_DIR"
# Obtener tamaño del directorio a respaldar
BACKUP_SIZE=$(du -sh "$SOURCE_DIR" 2>/dev/null | cut -f1)
echo -e "[*] Tamaño a procesar: $BACKUP_SIZE"
echo -e "[~] Comprimiendo y empaquetando... (esto puede tardar)"

# Inicializar variable para almacenar el PID del proceso tar
TAR_PID=""

# -----------------------------------------------------------------------------
# Función spinner: muestra una barra de progreso animada
# -----------------------------------------------------------------------------
# Args: $1 = PID del proceso a监控, $2 = mensaje a mostrar
spinner() {
    local pid=$1
    local msg=$2
    # Caracteres para la animación
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
# Ejecutar tar en segundo plano para permitir la barra de progreso
# -----------------------------------------------------------------------------
# Flags:
#   -c  : crear archivo
#   -z  : comprimir con gzip
#   -P  : rutas absolutas (no eliminar / inicial)
#   -f  : nombre del archivo
#   --listed-incremental: crear archivo de metadatos .snar para backups incrementales
#   --no-check-device: evitar problemas con dispositivos
#   &: ejecutar en segundo plano
tar -czPf "$FILENAME" \
   --listed-incremental="$SNAPSHOT_FILE" \
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
   echo -e "[+] Copia completa completada | Tamaño: $FINAL_SIZE"
else
   echo -e "[X] Error en el proceso de backup."
   # Eliminar el directorio si hubo error
   rm -rf "$DEST_DIR"
   exit 1
fi


