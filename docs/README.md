# Documentación — Tenebrio 3D Heatmap + AI Sentinel

Índice de toda la documentación del proyecto. Para empezar rápido, lee `../README.md` en la raíz.

## Mapa de documentos

### Cambios recientes (orden de lectura recomendado)

| Documento | Contenido |
|---|---|
| [`AGENTE_IA_CAMBIOS.md`](AGENTE_IA_CAMBIOS.md) | **Cambios añadidos en la rama `feature/agent-ia-conversacional`**: agente conversacional, bot Telegram bidireccional, widget de chat, gráficas inline, detector de saltos, cache Ubidots. Arquitectura, decisiones de diseño y operación. |
| [`INTEGRATION.md`](INTEGRATION.md) | Integración del dashboard 3D de Danny con el sidecar Python del predictor IA. Arranque rápido, estructura de archivos, troubleshooting general. |

### Componentes individuales

| Documento | Componente |
|---|---|
| [`ai-predictor.md`](ai-predictor.md) | Predictor IA (Python/FastAPI/GRU) — modelos, training, métricas |
| [`node-dashboard.md`](node-dashboard.md) | Dashboard 3D (Node.js/Express/Babylon.js) — heatmap volumétrico en tiempo real |
| [`node-changelog.md`](node-changelog.md) | Migración Python/Flask/Plotly → Node.js/Express/Babylon.js (histórico) |
| [`node-requirements.md`](node-requirements.md) | Requisitos del sistema para el dashboard Node |
| [`node-scripts-install.md`](node-scripts-install.md) | Guía de instalación como servicio Windows + kiosko Chrome |

### Por dónde empezar según el caso

- **¿Soy nuevo en el proyecto?** → `../README.md` → `INTEGRATION.md` → `AGENTE_IA_CAMBIOS.md`
- **¿Voy a desplegar en producción?** → `INTEGRATION.md` → `node-scripts-install.md` → `node-requirements.md`
- **¿Quiero entender el agente IA?** → `AGENTE_IA_CAMBIOS.md` (secciones 2-7)
- **¿Quiero usar/cambiar el predictor GRU?** → `ai-predictor.md`
- **¿Quiero modificar el dashboard 3D?** → `node-dashboard.md` → `node-changelog.md`
