// Historial: carga datos historicos desde Ubidots, slider de tiempo y
// re-render del frame seleccionado mediante /api/history/interpolate.
// Replica las funciones loadHistory, onTimeSlider, renderHistoryFrame del
// frontend Plotly original.

let historyData = null;
let historyMode = false;
let _onLiveData = null; // callback para empujar el frame al render
let _liveSnapshot = null;

export function setLiveDataProvider(getter) {
    // El app guarda la ultima respuesta /api/data y nos la pasa via getter
    _onLiveData = getter;
}

export function isHistoryMode() {
    return historyMode;
}

export function initHistoryUI({ onFrame }) {
    document.getElementById('btn-load-hist').addEventListener('click', () => loadHistory(onFrame));
    document.getElementById('btn-exit-history').addEventListener('click', exitHistory);
    document.getElementById('time-slider').addEventListener('input', (e) => {
        onTimeSlider(e.target.value, onFrame);
    });
}

async function loadHistory(onFrame) {
    const startVal = document.getElementById('hist-start').value;
    const endVal = document.getElementById('hist-end').value;
    if (!startVal || !endVal) return;

    const btn = document.getElementById('btn-load-hist');
    btn.disabled = true;
    btn.textContent = 'Cargando...';

    try {
        const resp = await fetch(`/api/history?start=${startVal}&end=${endVal}`);
        if (!resp.ok) throw new Error('Error');
        historyData = await resp.json();

        if (historyData.timestamps.length === 0) {
            btn.textContent = 'Sin datos';
            setTimeout(() => { btn.textContent = 'Cargar'; btn.disabled = false; }, 2000);
            return;
        }

        const slider = document.getElementById('time-slider');
        slider.min = 0;
        slider.max = historyData.timestamps.length - 1;
        slider.value = historyData.timestamps.length - 1;

        historyMode = true;
        document.getElementById('time-slider-wrap').classList.add('visible');
        onTimeSlider(slider.value, onFrame);

        btn.textContent = 'Cargar';
        btn.disabled = false;
    } catch {
        btn.textContent = 'Error';
        setTimeout(() => { btn.textContent = 'Cargar'; btn.disabled = false; }, 2000);
    }
}

let sliderTimeout = null;
function onTimeSlider(idx, onFrame) {
    if (!historyData || !historyData.timestamps.length) return;
    const ts = historyData.timestamps[idx];
    const date = new Date(ts);
    document.getElementById('ts-label').textContent =
        date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    if (sliderTimeout) clearTimeout(sliderTimeout);
    sliderTimeout = setTimeout(() => renderHistoryFrame(ts, onFrame), 200);
}

function findClosest(varData, targetTs) {
    if (!varData || varData.length === 0) return null;
    let closest = varData[0];
    let minDiff = Math.abs(varData[0].timestamp - targetTs);
    for (const v of varData) {
        const diff = Math.abs(v.timestamp - targetTs);
        if (diff < minDiff) { minDiff = diff; closest = v; }
        if (diff > minDiff) break;
    }
    return minDiff < 300000 ? closest.value : null;
}

async function renderHistoryFrame(ts, onFrame) {
    const tempValues = {};
    for (const [label, values] of Object.entries(historyData.temperature || {})) {
        tempValues[label] = findClosest(values, ts);
    }
    const humValues = {};
    for (const [label, values] of Object.entries(historyData.humidity || {})) {
        humValues[label] = findClosest(values, ts);
    }
    const rfValues = {};
    for (const [label, values] of Object.entries(historyData.radiant_floor || {})) {
        rfValues[label] = findClosest(values, ts);
    }
    const mrValues = {};
    for (const [label, values] of Object.entries(historyData.machine_room || {})) {
        mrValues[label] = findClosest(values, ts);
    }
    const otherValues = {};
    for (const [label, values] of Object.entries(historyData.other || {})) {
        otherValues[label] = findClosest(values, ts);
    }

    try {
        const params = new URLSearchParams({
            temps: JSON.stringify(tempValues),
            hums: JSON.stringify(humValues),
        });
        const resp = await fetch('/api/history/interpolate?' + params);
        if (!resp.ok) return;
        const volumes = await resp.json();

        const live = _onLiveData ? _onLiveData() : null;
        if (!live) return;

        // Clonar el ultimo frame en vivo y sustituir los campos
        const histData = JSON.parse(JSON.stringify(live));
        for (const [label, val] of Object.entries(tempValues)) {
            if (histData.sensors[label] && val !== null) histData.sensors[label].value = val;
        }
        if (tempValues['tex'] !== undefined) histData.exterior_temp = tempValues['tex'];
        if (tempValues['tps'] !== undefined) histData.avg_temp_superior = tempValues['tps'];
        if (tempValues['tpi'] !== undefined) histData.avg_temp_inferior = tempValues['tpi'];

        for (const [label, val] of Object.entries(humValues)) {
            if (val !== null) histData.humidity[label] = val;
        }
        for (const [label, val] of Object.entries(rfValues)) {
            if (histData.radiant_floor && histData.radiant_floor[label] && val !== null) {
                histData.radiant_floor[label].value = val;
            }
        }
        for (const [label, val] of Object.entries(mrValues)) {
            if (histData.machine_room && histData.machine_room[label] && val !== null) {
                histData.machine_room[label].value = val;
            }
        }
        if (otherValues['amoniaco'] !== undefined) histData.amoniaco = otherValues['amoniaco'];
        if (otherValues['ventilador'] !== undefined) histData.fan_on = otherValues['ventilador'] >= 1;
        if (otherValues['extractor'] !== undefined) histData.extractor_on = otherValues['extractor'] >= 1;

        if (volumes.volume_data) histData.volume_data = volumes.volume_data;
        if (volumes.humidity_volume_data) histData.humidity_volume_data = volumes.humidity_volume_data;

        onFrame(histData);
    } catch {
        // Ignorar errores intermitentes durante el slider
    }
}

function exitHistory() {
    historyMode = false;
    historyData = null;
    document.getElementById('time-slider-wrap').classList.remove('visible');
}
