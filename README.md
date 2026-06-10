# Linux Backup TUI

Aplicación en **Python** para crear copias de seguridad completas e incrementales desde una interfaz minimalista en la misma terminal de Linux.

La interfaz permite:

* Elegir el disco externo montado que se usará como origen.
* Confirmar o escribir el directorio de origen.
* Escribir el directorio destino fuera del disco de origen.
* Ejecutar backups completos, incrementales o diferenciales usando `tar --listed-incremental`.
* Verificar la integridad del `.tar.gz` al terminar.
* Guardar `manifest.json` y `backup.log` dentro de cada backup.
* Restaurar un `.tar.gz` en una carpeta destino segura; si eliges un incremental, restaura automáticamente la cadena óptima completa.
* Cancelar un proceso en curso con limpieza de archivos parciales cuando aplica.

## Uso

```bash
python3 backup_tui.py
```

Opcionalmente puedes hacerlo ejecutable:

```bash
chmod +x backup_tui.py
./backup_tui.py
```

## Controles

* `Tab`: avanzar de campo.
* `Shift+Tab`: retroceder de campo.
* Flechas arriba/abajo en el panel de discos: cambiar USB de origen.
* Flechas izquierda/derecha: cambiar USB de origen, acción o tipo de backup.
* `Enter`: confirmar USB como origen, editar un campo, alternar acción/tipo, iniciar la copia, restaurar o salir al terminar.
* `q` o `Esc`: abrir menú de salida con `Cancelar` seleccionado por defecto.
* `Ctrl+C`: salir directamente cuando no hay una operación en curso.
* `c`: cerrar el menú de salida.
* `c` o `Ctrl+C`: cancelar mientras se ejecuta un backup o restauración.



## Restauración

Cambia el campo `Acción` a `Restaurar backup`. El campo `Backup` intenta cargar automáticamente el último `.tar.gz` encontrado para el origen/USB actual; también puedes editarlo manualmente. Escribe una carpeta destino específica en `Restaurar en`. Si eliges `backup_INC.tar.gz`, la aplicación busca automáticamente el último `backup_FULL.tar.gz` anterior. Si existe un `backup_DIFF.tar.gz` posterior a ese completo y anterior al incremental elegido, usa el diferencial más reciente y salta los incrementales anteriores; después aplica solo los incrementales posteriores necesarios. Si eliges `backup_DIFF.tar.gz`, restaura `FULL + DIFF`. La extracción se hace dentro de esa carpeta y no directamente sobre rutas del sistema como `/`, `/home`, `/etc` o `/usr`.

## Origen y destino

* `Origen` es el disco o carpeta que quieres copiar. Si eliges un USB en la lista, ese USB pasa a ser el origen.
* `Destino` es una carpeta distinta donde se guardará la copia. No puede estar dentro del origen.

Ejemplo:

```text
USB elegido: /media/nico/B4B2-5FEC
Origen: /media/nico/B4B2-5FEC
Destino: /home/nico/Backups
```

En ese caso se copia el USB y el backup se guarda en `/home/nico/Backups`.

## Estructura generada

```text
destino/
└── carpeta_backups/
    ├── Iniciales/
    │   └── 01-03-2026_18-30-00_FULL/
    │       ├── backup_FULL.tar.gz
    │       └── metadatos.snar
    ├── Diferenciales/
    │   └── 02-03-2026_18-50-00_DIFF/
    │       ├── backup_DIFF.tar.gz
    │       ├── backup.log
    │       ├── manifest.json
    │       └── metadatos.snar
    └── Incrementales/
        └── 02-03-2026_19-10-00_INC/
            ├── backup_INC.tar.gz
            ├── backup.log
            ├── manifest.json
            └── metadatos.snar
```


## Estructura del código

* `backup_tui.py`: punto de entrada ejecutable.
* `backup_lib/tui.py`: estado principal y navegación de teclado.
* `backup_lib/render.py`: dibujo de pantalla, paneles, campos y resumen de restauración.
* `backup_lib/dialogs.py`: menú de salida y prompt de edición.
* `backup_lib/workflows.py`: conexión entre la TUI y las operaciones largas.
* `backup_lib/operations.py`: creación y restauración de backups.
* `backup_lib/archives.py`: snapshots, cadenas de restauración y último backup disponible.
* `backup_lib/devices.py`: detección de discos externos.
* `backup_lib/commands.py`: comandos del sistema, tamaños, validaciones de espacio y destino seguro.
* `backup_lib/models.py`: modelos y errores compartidos.
* `backup_lib/config.py`: constantes de configuración.

## Requisitos

* Linux
* Python 3.10 o superior
* `tar`
* `du`
* `lsblk`
* Permisos de lectura en origen y escritura en destino

## Cómo funcionan incremental y diferencial

* El incremental localiza el último `metadatos.snar`, sea de un completo, diferencial o incremental.
* El diferencial clona el `metadatos.snar` del último backup completo, por eso compara siempre contra ese completo.
* `tar` compara el estado actual con el snapshot clonado.
* Solo empaqueta archivos nuevos, modificados o eliminados respecto a ese snapshot.
* Al restaurar un incremental, se aplica primero el completo base; si hay un diferencial anterior al incremental elegido, se aplica el diferencial más reciente y se saltan los incrementales anteriores; después se aplican los incrementales posteriores hasta el seleccionado.

## Menú de salida

La esquina inferior derecha muestra `Esc menú`. Al pulsar `Esc` o `q`, aparece una ventana para confirmar `Salir` o volver con `Cancelar`. `Cancelar` aparece seleccionado por defecto para evitar salidas accidentales. `Ctrl+C` sale directamente cuando no hay una operación en curso.

## Finalización

Al completar una copia o restauración, el foco vuelve a `Acción`. Para salir con confirmación, usa `Esc` o `q`; para salir directo, usa `Ctrl+C`.

## Cancelación segura

Si presionas `c` o `Ctrl+C` durante el proceso:

* Se detiene el proceso `tar`.
* Se elimina la carpeta parcial.
* Se evita dejar backups corruptos.
