// Configuracion de logging con archivos diarios organizados por carpetas mensuales.
// Estructura generada:
//     logs/
//     +- 2026-04/
//        +- 2026-04-01.log
//        +- 2026-04-02.log
// Replica de backend/log_config.py adaptado a winston.

import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import winston from 'winston';
import DailyRotateFile from 'winston-daily-rotate-file';

import { LOG_LEVEL } from './config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Carpeta raiz de logs (relativa al proyecto)
const PROJECT_ROOT = path.resolve(__dirname, '..');
const LOGS_DIR = path.join(PROJECT_ROOT, 'logs');

// Asegura que la carpeta del mes actual exista
function ensureMonthFolder(date) {
  const yearMonth = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  const folder = path.join(LOGS_DIR, yearMonth);
  fs.mkdirSync(folder, { recursive: true });
  return folder;
}

ensureMonthFolder(new Date());

// Formato igual al de Python: "YYYY-MM-DD HH:MM:SS,ms [LEVEL] name: message"
const formatLine = winston.format.printf(({ timestamp, level, message, name }) => {
  const tag = name ? name : 'app';
  return `${timestamp} [${level.toUpperCase()}] ${tag}: ${message}`;
});

// Transport con rotacion diaria que escribe en logs/YYYY-MM/YYYY-MM-DD.log
const dailyTransport = new DailyRotateFile({
  filename: '%DATE%.log',
  datePattern: 'YYYY-MM-DD',
  dirname: path.join(LOGS_DIR, `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`),
  utc: false,
  zippedArchive: false,
  maxFiles: null,
});

// Cuando ocurre el rollover de medianoche, recolocar el archivo dentro de la
// carpeta YYYY-MM correspondiente (creandola si no existe).
dailyTransport.on('new', (newFilename) => {
  try {
    const today = new Date();
    const folder = ensureMonthFolder(today);
    const fileName = path.basename(newFilename);
    const targetPath = path.join(folder, fileName);
    if (path.resolve(newFilename) !== path.resolve(targetPath)) {
      // Reasignar dirname del transport para los siguientes escritos
      dailyTransport.dirname = folder;
    }
  } catch (e) {
    // Silencioso: si falla la reorganizacion, winston seguira escribiendo en el dir original
  }
});

const baseLogger = winston.createLogger({
  level: LOG_LEVEL,
  format: winston.format.combine(
    winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss,SSS' }),
    formatLine,
  ),
  transports: [
    new winston.transports.Console(),
    dailyTransport,
  ],
});

// Devuelve un logger "hijo" con un nombre fijo (similar a logging.getLogger(__name__))
export function getLogger(name) {
  return baseLogger.child({ name });
}

export default baseLogger;
