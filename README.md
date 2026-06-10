# Linux Backup TUI

Aplicación en **Python** para crear copias de seguridad completas e incrementales desde una interfaz minimalista en la misma terminal de Linux.

La interfaz permite:

* Elegir el disco externo montado que se usará como origen.
* Confirmar o escribir el directorio de origen.
* Escribir el directorio destino fuera del disco de origen.
* Ejecutar backup completo o incremental usando `tar --listed-incremental`.
* Cancelar un proceso en curso con limpieza de archivos parciales.

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

* `Tab`: cambiar de campo.
* Flechas arriba/abajo en el panel de discos: cambiar USB de origen.
* Flechas izquierda/derecha: cambiar USB de origen o tipo de backup.
* `Enter`: confirmar USB como origen, editar un campo, alternar tipo, iniciar la copia o salir al terminar.
* `q`: salir directamente.
* `Esc`: abrir menú con `Salir` y `Cancelar`.
* `c` o `Ctrl+C`: cancelar mientras se ejecuta un backup.


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
    └── Incrementales/
        └── 02-03-2026_19-10-00_INC/
            ├── backup_INC.tar.gz
            └── metadatos.snar
```

## Requisitos

* Linux
* Python 3.10 o superior
* `tar`
* `du`
* `lsblk`
* Permisos de lectura en origen y escritura en destino

## Cómo funciona el incremental

* Se localiza el último `metadatos.snar`.
* Se clona para mantener la cadena intacta.
* `tar` compara el estado actual con el snapshot.
* Solo empaqueta archivos nuevos, modificados o eliminados.

## Menú de salida

La esquina inferior derecha muestra `Esc menú`. Al pulsar `Esc`, aparece una ventana pequeña para confirmar `Salir` o volver con `Cancelar`.

## Finalización

Al completar una copia, el botón principal cambia a `Salir`. Pulsa `Enter` para cerrar la interfaz.

## Cancelación segura

Si presionas `c` o `Ctrl+C` durante el proceso:

* Se detiene el proceso `tar`.
* Se elimina la carpeta parcial.
* Se evita dejar backups corruptos.
