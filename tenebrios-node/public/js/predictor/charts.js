// Charts overlay (real vs predicho +3min) por grupo TEMP/HUM. Portado de
// app/static/app.js del proyecto Modelos_Tenebrios. Estilizado con la
// paleta de Danny (fondo oscuro, ejes finos).

const fmtTime = (sec) => {
    if (!sec) return '—';
    return new Date(sec * 1000).toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
};

const charts = {};

export function initMainChart(group, vars, hues, unit) {
    const el = document.getElementById(`ai-chart-${group.toLowerCase()}`);
    if (!el || typeof echarts === 'undefined') return;
    const c = echarts.init(el, null, { renderer: 'canvas' });
    charts[group] = c;

    const series = [];
    vars.forEach((v, i) => {
        series.push({
            name: v,
            type: 'line',
            showSymbol: false,
            smooth: true,
            lineStyle: { width: 1.6, color: hues[i] },
            emphasis: { focus: 'series' },
            data: [],
        });
        series.push({
            name: v + ' pred',
            type: 'line',
            showSymbol: false,
            smooth: true,
            lineStyle: { width: 1.2, color: hues[i], type: 'dashed', opacity: 0.7 },
            emphasis: { focus: 'series' },
            data: [],
        });
    });

    c.setOption({
        backgroundColor: 'transparent',
        animation: true,
        animationDuration: 250,
        grid: { left: 36, right: 12, top: 18, bottom: 26 },
        legend: {
            data: vars,
            textStyle: { color: '#8aa0b0', fontSize: 10, fontFamily: 'JetBrains Mono' },
            top: 0, right: 0,
            icon: 'roundRect',
            itemWidth: 10, itemHeight: 3,
        },
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26,38,48,0.94)',
            borderColor: '#3a5a6a',
            textStyle: { color: '#e8e0d8' },
            valueFormatter: (v) => v == null ? '—' : v.toFixed(2) + unit,
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            axisLabel: { color: '#607888', fontSize: 10, fontFamily: 'JetBrains Mono' },
            splitLine: { show: false },
            data: [],
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLine: { show: false },
            axisLabel: {
                color: '#607888', fontSize: 10, fontFamily: 'JetBrains Mono',
                formatter: (v) => v.toFixed(1),
            },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } },
        },
        series,
    });
}

export function refreshMainChart(group, vars, history) {
    const c = charts[group];
    if (!c) return;
    const xs = history.map((p) => fmtTime(p.ts));
    const series = [];
    vars.forEach((v) => {
        series.push({ data: history.map((p) => p.current[v]) });
        series.push({ data: history.map((p) => p.predicted[v]) });
    });
    c.setOption({
        xAxis: { data: xs },
        series,
    });
}

export function resizeMainCharts() {
    Object.values(charts).forEach((c) => c.resize());
}
