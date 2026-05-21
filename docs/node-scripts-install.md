# Guía de migración e instalación — Tenebrio 3D Heatmap (Node.js)

Esta guía cubre cómo desinstalar el proyecto anterior (Python/Flask) e instalar la nueva versión en Node.js como servicio de Windows con arranque automático y kiosko en Chrome.

---

## Prerequisitos

Antes de ejecutar cualquier script, verifica que tienes instalado lo siguiente:

| Requisito | Versión mínima | Descarga |
|-----------|---------------|----------|
| **Node.js** | 20 LTS | https://nodejs.org/ |
| **NSSM** | cualquiera | https://nssm.cc/download |
| **Google Chrome** | cualquiera | https://www.google.com/chrome/ |

### Instalar NSSM

1. Descarga el `.zip` desde https://nssm.cc/download
2. Extrae el ejecutable `nssm.exe` (carpeta `win64/`)
3. Cópialo a `C:\Windows\System32\`
4. Verifica en una terminal: `nssm version`

---

## Paso 1 — Eliminar el servicio anterior (Python)

> Si el equipo nunca tuvo el proyecto Python instalado como servicio, salta al Paso 2.

Ejecuta como administrador:

```
scripts\remove_old_service.bat
```

Este script elimina:
- El servicio Windows `TenebrioHeatmap` (Python/Flask vía NSSM)
- Procesos Python residuales y libera el puerto 5000
- Entradas antiguas de kiosko en la carpeta Startup
- Políticas de registro que bloqueaban Microsoft Edge

---

## Paso 2 — Configurar el proyecto

Desde la carpeta `tenebrios-node/`:

```bat
copy .env.example .env
```

Abre `.env` y completa los valores:

```env
UBIDOTS_TOKEN=tu_token_aqui
DEVICE_LABEL=tenebrios
WEB_PORT=5000
```

---

## Paso 3 — Instalar dependencias npm

Ejecuta `setup.bat` (o manualmente `npm install`) para instalar las dependencias:

```bat
scripts\setup.bat
```

---

## Paso 4 — Instalar el servicio Node.js

Ejecuta como administrador:

```
scripts\install_service.bat
```

El script realiza lo siguiente de forma automática:

1. Verifica permisos, NSSM y Node.js
2. Crea la carpeta `logs/`
3. Instala el servicio Windows `TenebrioNode` (arranca con la PC)
4. Configura logs en `logs/service.log` con reinicio automático ante fallos
5. Inicia el servicio
6. Copia `open_kiosk.bat` a la carpeta Startup del usuario (se ejecuta al iniciar sesión)
7. Abre Chrome en modo kiosko apuntando a `http://localhost:5000`

Al terminar, el equipo queda configurado para:
- Iniciar el servidor automáticamente al encender
- Abrir Chrome en pantalla completa al iniciar sesión de Windows

---

## Mantenimiento

### Actualizar dependencias y reiniciar el servicio

Cuando actualices el código o el `package.json`:

```
scripts\update_service.bat
```

Detiene el servicio, ejecuta `npm install` y lo reinicia.

### Desinstalar todo

Para revertir **todos** los cambios que hizo `install_service.bat`:

```
scripts\uninstall_service.bat
```

Elimina el servicio, cierra el kiosko, borra la entrada de Startup y restaura la barra de tareas.

---

## Comandos útiles post-instalación

Desde cualquier terminal con privilegios de administrador:

```bat
nssm status TenebrioNode       :: Ver estado del servicio
nssm start  TenebrioNode       :: Iniciar
nssm stop   TenebrioNode       :: Detener
nssm restart TenebrioNode      :: Reiniciar
```

Logs del servidor:

```
tenebrios-node\logs\service.log
```

---

## Estructura de scripts

```
scripts/
├── install_service.bat     Instala el servicio Node + kiosko
├── update_service.bat      npm install + reinicio del servicio
├── uninstall_service.bat   Desinstala todo, restaura el sistema
├── remove_old_service.bat  Elimina el servicio Python anterior
├── open_kiosk.bat          Abre Chrome en kiosko (copiado a Startup)
├── setup.bat               Instala dependencias npm (Windows)
└── setup.sh                Instala dependencias npm (Linux/Mac)
```

---

## Resolución de problemas

**El servicio no arranca**
- Revisa `tenebrios-node\logs\service.log`
- Verifica que el archivo `.env` existe y tiene `UBIDOTS_TOKEN`
- Comprueba que el puerto 5000 no está ocupado: `netstat -ano | findstr :5000`

**Chrome no abre en kiosko al iniciar sesión**
- Verifica que `TenebrioKiosk.bat` existe en `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
- Si no está, vuelve a ejecutar `install_service.bat` como administrador

**La barra de tareas sigue oculta tras desinstalar**
- Ejecuta `uninstall_service.bat` como administrador; el paso 6 la restaura automáticamente
- O manualmente: clic derecho en la barra de tareas → Configuración → desactivar "Ocultar automáticamente la barra de tareas"
