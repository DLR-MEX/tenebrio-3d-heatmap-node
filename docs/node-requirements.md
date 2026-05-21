# Requisitos - TENEBRIOS 3D

## Requerimientos del Sistema

### Software Requerido
- **Node.js**: >= 20.0.0
- **npm**: >= 10.0.0 (incluido con Node.js)

## Dependencias del Proyecto

### Producción
- **express** (^4.19.2) - Servidor web y API REST
- **mqtt** (^5.10.0) - Cliente MQTT para conexión a Ubidots
- **dotenv** (^16.4.5) - Gestión de variables de entorno
- **winston** (^3.13.1) - Sistema de logging
- **winston-daily-rotate-file** (^5.0.0) - Rotación diaria de logs

### Desarrollo
- **vitest** (^1.6.0) - Framework de testing

## Instalación

### Windows
```batch
setup.bat
```

### Linux / macOS
```bash
bash setup.sh
```

### Instalación Manual
1. Instalar Node.js desde https://nodejs.org/
2. Verificar instalación: `node --version` y `npm --version`
3. Ejecutar: `npm install`
4. Crear `.env` basado en `.env.example`

## Verificación

Después de instalar, verifica que todo funciona:

```bash
npm start        # Inicia el servidor
npm run dev      # Inicia con hot-reload
npm run test     # Ejecuta tests
npm run simulator # Inicia simulador MQTT
```

## Archivos de Configuración

- `.env.example` - Plantilla de variables de entorno
- `.env` - Variables de entorno (crear a partir del ejemplo)
- `package.json` - Definición de dependencias y scripts
