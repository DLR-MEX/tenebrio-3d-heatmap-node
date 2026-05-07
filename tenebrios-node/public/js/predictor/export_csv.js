// Exporta el historial en memoria de la vista IA a CSV (descarga directa).
//
// Limitacion: el history vive en RAM y guarda hasta MAX_POINTS (~60)
// puntos. Para historial completo hay que descargarlo de Ubidots (futuro).
// Esto se documenta como comentario en la primera linea del CSV.
//
// Uso:
//   initCsvExport({
//       getHistory: (group) => [...],
//       getVars: (group) => ['t1', 't2', ...],
//   });
// El modulo conecta los listeners a los botones [data-group="TEMP"|"HUM"].

let providers = null;

export function initCsvExport(p) {
    providers = p;
    document.querySelectorAll('.ai-export-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const group = btn.dataset.group;
            if (!group) return;
            try {
                downloadCsv(group);
            } catch (err) {
                console.error('[export-csv]', err);
                alert('No se pudo generar el CSV: ' + err.message);
            }
        });
    });
}

function downloadCsv(group) {
    if (!providers) return;
    const history = providers.getHistory(group) || [];
    const vars = providers.getVars(group) || [];
    if (history.length === 0) {
        alert('Aun no hay datos en memoria para exportar. Espera a que llegue al menos una prediccion.');
        return;
    }

    // Header del archivo: comentario + nombres de columna.
    // Columnas: timestamp_iso, timestamp_unix, var, var_pred, alerts...
    const lines = [];
    const now = new Date().toISOString();
    lines.push(`# Tenebris AI Sentinel — export ${group} @ ${now}`);
    lines.push(`# History en memoria, max 60 puntos. Para historico completo ver Ubidots.`);

    const headerCols = ['timestamp_iso', 'timestamp_unix'];
    vars.forEach((v) => headerCols.push(v, `${v}_pred`, `${v}_alert_cur`, `${v}_alert_pred`));
    lines.push(headerCols.map(csvEscape).join(','));

    history.forEach((p) => {
        const tsIso = new Date((p.ts || 0) * 1000).toISOString();
        const row = [tsIso, p.ts || ''];
        vars.forEach((v) => {
            const cur = p.current?.[v];
            const pred = p.predicted?.[v];
            const alert = p.alerts?.[v] || {};
            row.push(
                Number.isFinite(cur) ? cur.toFixed(3) : '',
                Number.isFinite(pred) ? pred.toFixed(3) : '',
                alert.current || '',
                alert.predicted || '',
            );
        });
        lines.push(row.map(csvEscape).join(','));
    });

    const csv = lines.join('\r\n') + '\r\n';
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const stamp = now.replace(/[-:T.]/g, '').slice(0, 14);
    const filename = `tenebris_${group.toLowerCase()}_${stamp}.csv`;

    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function csvEscape(value) {
    if (value === null || value === undefined) return '';
    const s = String(value);
    if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
}
