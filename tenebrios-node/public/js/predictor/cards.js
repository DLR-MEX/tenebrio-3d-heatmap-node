// Tarjetas por sensor para vista IA: valor actual, predicho +3min, delta
// y mini-sparkline con historial reciente. Portado de app/static/app.js
// del proyecto Modelos_Tenebrios, adaptado a la paleta de Danny.

const fmt = (n, d = 2) => Number.isFinite(n) ? n.toFixed(d) : '—';

// Almacen de instancias ECharts por sensor (para no recrearlas cada update)
const sparks = { TEMP: {}, HUM: {} };

export function buildCards(group, vars, hues) {
    const root = document.getElementById(`ai-cards-${group.toLowerCase()}`);
    if (!root) return;
    root.innerHTML = '';
    vars.forEach((v, i) => {
        const card = document.createElement('div');
        // Arranca en estado "loading" — los placeholders muestran shimmer
        // hasta que llegue el primer SSE/snapshot con datos para este sensor.
        card.className = 'ai-sensor loading';
        card.style.setProperty('--hue', hues[i]);
        card.dataset.var = v;
        card.innerHTML = `
            <div class="ai-sensor-row">
                <span class="ai-sensor-label">${v}</span>
                <span class="ai-sensor-delta flat skeleton skeleton-pill" data-role="delta">&nbsp;</span>
            </div>
            <div class="ai-sensor-value skeleton skeleton-value" data-role="value">&nbsp;</div>
            <div class="ai-sensor-pred">
                <span class="arrow">→</span><span class="skeleton skeleton-pred" data-role="pred">&nbsp;</span><span class="pred-suffix">+3min</span>
            </div>
            <div class="ai-sensor-status unknown skeleton skeleton-pill" data-role="status">&nbsp;</div>
            <div class="ai-sensor-spark" data-role="spark"></div>
        `;
        root.appendChild(card);
    });
}

export function updateCard(group, vars, idx, current, predicted, alerts, history, unit) {
    const v = vars[idx];
    const card = document.querySelector(`#ai-cards-${group.toLowerCase()} [data-var="${v}"]`);
    if (!card) return;

    const cur = current[v];
    const pred = predicted[v];
    const delta = pred - cur;
    const a = alerts?.[v] || { current: 'unknown', predicted: 'unknown' };

    // Una vez llega data, removemos los skeletons (idempotente).
    if (card.classList.contains('loading')) {
        card.classList.remove('loading');
        card.querySelectorAll('.skeleton').forEach((el) => {
            el.classList.remove('skeleton', 'skeleton-pill', 'skeleton-value', 'skeleton-pred');
        });
    }

    card.querySelector('[data-role="value"]').textContent = `${fmt(cur)}${unit}`;
    card.querySelector('[data-role="pred"]').textContent = `${fmt(pred)}${unit}`;

    const deltaEl = card.querySelector('[data-role="delta"]');
    deltaEl.textContent = (delta >= 0 ? '+' : '') + fmt(delta, 3);
    deltaEl.classList.remove('up', 'down', 'flat');
    if (delta > 0.01) deltaEl.classList.add('up');
    else if (delta < -0.01) deltaEl.classList.add('down');
    else deltaEl.classList.add('flat');

    // Estado: marca card y valor segun la clasificacion del backend.
    // - data-cur-state: estado actual (red border si abnormal hoy)
    // - data-pred-state: estado +3min (red en valor predicho si va a ser abnormal)
    card.dataset.curState = a.current;
    card.dataset.predState = a.predicted;

    // Pill de texto debajo del valor predicho. Las cuatro variantes:
    //   - PELIGRO        (rojo)    : valor actual fuera de rango
    //   - Alerta +3min   (naranja) : actual ok pero predicho fuera de rango
    //   - Normal         (verde)   : ambos dentro
    //   - —              (gris)    : sin clasificar (sin datos aun)
    const statusEl = card.querySelector('[data-role="status"]');
    if (statusEl) {
        let label, cls;
        if (a.current === 'abnormal') {
            label = 'PELIGRO';
            cls = 'danger';
        } else if (a.predicted === 'abnormal') {
            label = 'Alerta +3min';
            cls = 'warn';
        } else if (a.current === 'unknown' || a.predicted === 'unknown') {
            label = '—';
            cls = 'unknown';
        } else {
            label = 'Normal';
            cls = 'normal';
        }
        statusEl.textContent = label;
        statusEl.classList.remove('normal', 'warn', 'danger', 'unknown');
        statusEl.classList.add(cls);
    }

    // Animacion sutil al actualizar (Danny usa dorado, mantengo coherencia)
    card.dataset.flash = '1';
    setTimeout(() => card.removeAttribute('data-flash'), 600);

    renderSpark(group, v, card.querySelector('[data-role="spark"]'), history);
}

function renderSpark(group, varName, el, history) {
    if (!el || typeof echarts === 'undefined') return;
    let chart = sparks[group][varName];
    if (!chart) {
        chart = echarts.init(el, null, { renderer: 'svg' });
        sparks[group][varName] = chart;
    }
    const series = history.map((p) => p.current[varName]);
    chart.setOption({
        animation: false,
        grid: { left: 0, right: 0, top: 2, bottom: 2 },
        xAxis: { type: 'category', show: false, data: series.map((_, i) => i) },
        yAxis: { type: 'value', show: false, scale: true },
        tooltip: { show: false },
        series: [{
            type: 'line',
            data: series,
            showSymbol: false,
            smooth: true,
            lineStyle: { width: 1.5, color: '#8aa0b0' },
            areaStyle: { color: 'rgba(232,184,48,0.10)' },
        }],
    });
}

export function resizeSparks() {
    for (const g of Object.values(sparks)) {
        for (const c of Object.values(g)) c.resize();
    }
}
