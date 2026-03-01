# 🐧 Linux Backup Scripts – Full & Incremental

Scripts en **Bash** para realizar copias de seguridad completas e incrementales usando `tar` y `--listed-incremental`, con control de errores, limpieza automática y barra de progreso tipo spinner.

---

## 📦 Características

* ✅ Backup **completo (FULL)** comprimido en `.tar.gz`
* 🔁 Backup **incremental (INC)** basado en archivo `.snar`
* 🧠 Gestión automática de metadatos
* 🧹 Limpieza segura al cancelar con `Ctrl+C`
* 📊 Spinner visual mientras `tar` está en ejecución
* 📁 Estructura organizada por fechas

---

## 🗂️ Estructura generada

```
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

---

## 🚀 Uso

### 1️⃣ Backup completo

```bash
./inicial.sh <origen> [destino]
```

Ejemplo:

```bash
./inicial.sh /home/nico /media/backup
```

Si no se indica destino, usa el directorio actual.

---

### 2️⃣ Backup incremental

```bash
./incremental.sh <origen> [destino]
```

Ejemplo:

```bash
./incremental.sh /home/nico /media/backup
```

⚠️ Requiere haber ejecutado antes el backup completo.

---

## ⚙️ Requisitos

* Linux
* `bash`
* `tar`
* `du`
* `find`
* Permisos de lectura en origen y escritura en destino

---

## 🧠 Cómo funciona el incremental

* Se localiza el último `metadatos.snar`
* Se clona para mantener la cadena intacta
* `tar` compara el estado actual con el snapshot
* Solo empaqueta archivos nuevos, modificados o eliminados

---

## 🛑 Cancelación segura

Si presionas `Ctrl+C`:

* Se mata el proceso `tar`
* Se elimina la carpeta parcial
* Se evita dejar backups corruptos

