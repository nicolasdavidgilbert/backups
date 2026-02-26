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

### Backup completo

Copia todos los archivos del SSD al directorio `completo/<fecha>/` usando rsync con:
- `-a` (archive): preserva permisos, propietarios, timestamps, etc.
- `--delete`: elimina archivos del destino que ya no existen en el origen
- `--info=progress2`: muestra progreso de la transferencia

### Backup incremental

Usa rsync con `--link-dest` apuntando al último backup (completo o incremental). Esto crea hard links a los archivos no modificados, ahorrando espacio en disco.

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
