(() => {
  'use strict';

  const TEMP_VARS = ['t1', 't2', 't3', 't4', 't5', 'tex'];
  const HUM_VARS  = ['h1', 'h2', 'h3', 'h4', 'h5', 'hex'];

  // Paleta por sensor (consistente entre cards y chart)
  const TEMP_HUES = ['#38bdf8','#22d3ee','#a78bfa','#f472b6','#fb923c','#facc15'];
  const HUM_HUES  = ['#34d399','#10b981','#06b6d4','#3b82f6','#8b5cf6','#f43f5e'];

  const MAX_POINTS = 60;

  const state = {
    TEMP: { history: [], spark: {} },
    HUM:  { history: [], spark: {} },
  };

  // ---------- helpers ----------

  const fmt = (n, d = 2) => Number.isFinite(n) ? n.toFixed(d) : '—';
  const fmtTime = (sec) => {
    if (!sec) return '—';
    const d = new Date(sec * 1000);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  function setStatus(connected, label) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    dot.className = 'w-2 h-2 rounded-full ' + (connected ? 'live' : 'dead');
    text.textContent = label;
  }

  function setBufferChip(group, size, target) {
    const chip = document.getElementById(`buffer-${group.toLowerCase()}`);
    if (!chip) return;
    if (size >= target) {
      chip.classList.remove('visible');
      chip.textContent = '';
      return;
    }
    chip.classList.add('visible');
    chip.textContent = `buffer ${size}/${target}`;
  }

  // ---------- cards ----------

  function buildCards(group, vars, hues) {
    const root = document.getElementById(`cards-${group.toLowerCase()}`);
    root.innerHTML = '';
    vars.forEach((v, i) => {
      const card = document.createElement('div');
      card.className = 'sensor';
      card.style.setProperty('--hue', hues[i]);
      card.dataset.var = v;
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <span class="label">${v}</span>
          <span class="delta flat" data-role="delta">—</span>
        </div>
        <div class="value" data-role="value">—</div>
        <div class="pred"><span class="arrow">→</span><span data-role="pred">—</span><span class="text-zinc-600 text-[10px] ml-1">+3min</span></div>
        <div class="spark" data-role="spark"></div>
      `;
      root.appendChild(card);
    });
  }

  function updateCard(group, vars, idx, current, predicted, unit) {
    const v = vars[idx];
    const card = document.querySelector(`#cards-${group.toLowerCase()} [data-var="${v}"]`);
    if (!card) return;

    const cur = current[v];
    const pred = predicted[v];
    const delta = pred - cur;

    card.querySelector('[data-role="value"]').textContent = `${fmt(cur)}${unit}`;
    card.querySelector('[data-role="pred"]').textContent = `${fmt(pred)}${unit}`;

    const deltaEl = card.querySelector('[data-role="delta"]');
    deltaEl.textContent = (delta >= 0 ? '+' : '') + fmt(delta, 3);
    deltaEl.classList.remove('up', 'down', 'flat');
    if (delta > 0.01) deltaEl.classList.add('up');
    else if (delta < -0.01) deltaEl.classList.add('down');
    else deltaEl.classList.add('flat');

    // flash
    card.dataset.flash = '1';
    setTimeout(() => card.removeAttribute('data-flash'), 600);

    // sparkline
    renderSpark(group, v, card.querySelector('[data-role="spark"]'));
  }

  function renderSpark(group, varName, el) {
    if (!el) return;
    let chart = state[group].spark[varName];
    if (!chart) {
      chart = echarts.init(el, null, { renderer: 'svg' });
      state[group].spark[varName] = chart;
    }
    const series = state[group].history.map(p => p.current[varName]);
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
        lineStyle: { width: 1.5, color: '#a1a1aa' },
        areaStyle: { color: 'rgba(161,161,170,0.10)' },
      }],
    });
  }

  // ---------- main charts ----------

  const charts = {};

  function initMainChart(group, vars, hues, unit) {
    const el = document.getElementById(`chart-${group.toLowerCase()}`);
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
        textStyle: { color: '#a1a1aa', fontSize: 10, fontFamily: 'JetBrains Mono' },
        top: 0,
        right: 0,
        icon: 'roundRect',
        itemWidth: 10,
        itemHeight: 3,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(12,14,21,0.92)',
        borderColor: 'rgba(255,255,255,0.08)',
        textStyle: { color: '#e4e4e7', fontFamily: 'Inter' },
        valueFormatter: v => v == null ? '—' : v.toFixed(2) + unit,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        axisLabel: { color: '#52525b', fontSize: 10, fontFamily: 'JetBrains Mono' },
        splitLine: { show: false },
        data: [],
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisLabel: {
          color: '#52525b',
          fontSize: 10,
          fontFamily: 'JetBrains Mono',
          formatter: v => v.toFixed(1),
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)', type: 'dashed' } },
      },
      series,
    });
  }

  function refreshMainChart(group, vars) {
    const c = charts[group];
    if (!c) return;
    const hist = state[group].history;
    const xs = hist.map(p => fmtTime(p.ts));
    const series = [];
    vars.forEach((v) => {
      series.push({ data: hist.map(p => p.current[v]) });
      series.push({ data: hist.map(p => p.predicted[v]) });
    });
    c.setOption({
      xAxis: { data: xs },
      series,
    });
  }

  // ---------- snapshot / update ----------

  function applySnapshot(snap) {
    document.getElementById('device-label').textContent = snap.device || '—';
    setStatus(snap.mqtt_connected, snap.mqtt_connected ? 'online' : 'offline');

    for (const group of ['TEMP', 'HUM']) {
      const g = snap.groups[group];
      state[group].history = (g.history || []).slice(-MAX_POINTS);
      setBufferChip(group, g.buffer_size, 30);
      const vars = g.vars;
      const unit = group === 'TEMP' ? '°' : '%';
      if (g.ts && Object.keys(g.current).length) {
        for (let i = 0; i < vars.length; i++) {
          updateCard(group, vars, i, g.current, g.predicted, unit);
        }
      }
      refreshMainChart(group, vars);
    }
    if (snap.now) document.getElementById('last-update').textContent = fmtTime(snap.now);
  }

  function applyUpdate(payload) {
    if (payload.type === 'status') {
      setStatus(payload.mqtt_connected, payload.mqtt_connected ? 'online' : 'offline');
      return;
    }
    if (payload.type === 'buffer') {
      setBufferChip(payload.group, payload.size, payload.target);
      return;
    }
    if (payload.type === 'prediction') {
      const group = payload.group;
      const vars  = payload.vars;
      const unit  = group === 'TEMP' ? '°' : '%';

      state[group].history.push({
        ts: payload.ts,
        current: payload.current,
        predicted: payload.predicted,
      });
      if (state[group].history.length > MAX_POINTS) {
        state[group].history.shift();
      }

      for (let i = 0; i < vars.length; i++) {
        updateCard(group, vars, i, payload.current, payload.predicted, unit);
      }
      refreshMainChart(group, vars);
      setBufferChip(group, 30, 30);

      document.getElementById('last-update').textContent = fmtTime(payload.ts);
    }
  }

  // ---------- SSE ----------

  let es;
  function connect() {
    es = new EventSource('/api/stream');
    es.addEventListener('snapshot', e => {
      try { applySnapshot(JSON.parse(e.data)); } catch (err) { console.error(err); }
    });
    es.addEventListener('update', e => {
      try { applyUpdate(JSON.parse(e.data)); } catch (err) { console.error(err); }
    });
    es.addEventListener('ping', () => {});
    es.onerror = () => {
      setStatus(false, 'reconectando…');
      es.close();
      setTimeout(connect, 2000);
    };
  }

  // ---------- init ----------

  buildCards('TEMP', TEMP_VARS, TEMP_HUES);
  buildCards('HUM',  HUM_VARS,  HUM_HUES);
  initMainChart('TEMP', TEMP_VARS, TEMP_HUES, '°');
  initMainChart('HUM',  HUM_VARS,  HUM_HUES,  '%');

  window.addEventListener('resize', () => {
    Object.values(charts).forEach(c => c.resize());
    Object.values(state.TEMP.spark).forEach(c => c.resize());
    Object.values(state.HUM.spark).forEach(c => c.resize());
  });

  connect();
})();
