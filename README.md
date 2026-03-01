# backups

Script de backup para discos SSD externos usando rsync.

## Uso

```bash
backups < -c | --completo | -i | --incremental > <SSD>
```

### Opciones

| Opción | Descripción |
|--------|-------------|
| `-c`, `--completo` | Realizar backup completo |
| `-i`, `--incremental` | Realizar backup incremental |
| `-h`, `--help` | Mostrar ayuda |
| `-v`, `--version` | Mostrar versión |

### Ejemplos

```bash
# Backup completo
sudo backups -c MiSSD

# Backup incremental
sudo backups --incremental MiSSD
```

## Cómo funciona

### Estructura de directorios

El script crea la siguiente estructura en `/backups/<SSD>/`:

```
/backups/MiSSD/
├── completo/
│   └── 2026-02-26/
├── incrementales/
    └── 2026-02-26/
```

### Flujo general

Antes de ejecutar cualquier backup, el script:

1. **Analiza** los archivos que se transferirán
2. **Calcula** el tamaño total y cantidad de archivos/cambios
3. **Solicita confirmación** al usuario: `▶ Continuar? [S/n]`
   - Por defecto continúa (Intro = sí, `n` = cancelar)
4. **Ejecuta rsync** si el usuario confirma

Esta lógica está centralizada en la función `ask_continue()`.

### Backup completo

Copia todos los archivos del SSD al directorio `completo/<fecha>/` usando rsync con:
- `-a` (archive): preserva permisos, propietarios, timestamps, etc.
- `--delete`: elimina archivos del destino que ya no existen en el origen
- `--info=progress2`: muestra progreso de la transferencia

### Backup incremental

Ejecuta primero un análisis simulado con `rsync -ai` para mostrar:
- Referencia (último backup usado como base)
- Archivos que cambiarán
- Tamaño aproximado de los cambios

Luego usa rsync con `--link-dest` apuntando al último backup (completo o incremental). Esto crea hard links a los archivos no modificados, ahorrando espacio en disco.

**Requisito**: debe existir al menos un backup completo previo.

### Validación de argumentos

El script usa arrays para definir los modificadores válidos:

```bash
VALID_MODE_FLAGS=("-c" "--completo" "-i" "--incremental")
VALID_INFO_FLAGS=("-h" "--help" "-v" "--version")
```

La verificación se hace con coincidencia de patrones:

```bash
[[ " ${VALID_MODE_FLAGS[*]} " =~ " ${MODE} " ]]
```

Esto permite agregar nuevos modificadores fácilmente añadiendo elementos al array.

### Permisos

El script debe ejecutarse con sudo para acceder a los directorios del SSD en `/media/`.

## Scripts disponibles

Existen dos enfoques de backup:

### Enfoque 1: rsync (script principal)

El script principal `backups.sh` ubicado en `/usr/local/bin/backups` usa rsync para realizar backups.

### Enfoque 2: tar (scripts alternativos)

Alternativamente, se pueden usar los scripts `inicial.sh` e `incremental.sh` que usan `tar` con `--listed-incremental` para crear backups comprimidos en formato `.tar.gz`.

#### inicial.sh - Backup completo

```bash
./inicial.sh <origen> [destino]
```

- **origen**: Directorio a respaldar
- **destino** (opcional): Directorio donde se guardará el backup (por defecto, directorio actual)

Crea la estructura:
```
<nombre>_backups/
└── Iniciales/
    └── dd-mm-YYYY_HH-MM-SS_FULL/
        ├── backup_FULL.tar.gz
        └── metadatos.snar
```

#### incremental.sh - Backup incremental

```bash
./incremental.sh <origen> [destino]
```

- Requiere que exista un backup completo previo (creado con `inicial.sh`)
- Usa el archivo de metadatos `.snar` del último backup

Crea la estructura:
```
<nombre>_backups/
└── Incrementales/
    └── dd-mm-YYYY_HH-MM-SS_INC/
        ├── backup_INC.tar.gz
        └── metadatos.snar
```

### Ejemplos

```bash
# Backup completo con tar
./inicial.sh /media/usuario/MiSSD /backups

# Backup incremental con tar
./incremental.sh /media/usuario/MiSSD /backups
```

## Instalación

1. Copiar el script a una ruta del PATH:

```bash
sudo cp backups.sh /usr/local/bin/backups
```

2. Dar permisos de ejecución:

```bash
sudo chmod +x /usr/local/bin/backups
```

3. Verificar instalación:

```bash
backups --version
```

Reemplaza `MiSSD` por el nombre de tu disco SSD (el nombre que aparece en `/media/<usuario>/MiSSD/`).
