// Widget de chat IA: boton flotante + panel deslizable.
// Usa /api/predictor/agent/chat via Express -> sidecar Python.
// Historial vive en localStorage (max 30 mensajes); cada turno
// reenvia el history al backend (el LLM no tiene memoria propia).

const ENDPOINT = '/api/predictor/agent/chat';
const STORAGE_KEY = 'ai-chat-history-v1';
const MAX_HISTORY = 30;
const REQUEST_TIMEOUT_MS = 95000;

// Sugerencias para la primera interaccion. Cada chip dispara la pregunta
// como si el usuario la hubiera tipeado y enviado.
const SUGGESTED_PROMPTS = [
    { icon: '🌡', text: '¿Cómo está el cuarto ahora?' },
    { icon: '🚨', text: '¿Hubo anomalías hoy?' },
    { icon: '📈', text: 'Gráfica de temperaturas últimas 6 horas' },
    { icon: '💧', text: '¿Desde cuándo está mal la humedad?' },
    { icon: '🔥', text: '¿Cómo está el termo y el calentador?' },
    { icon: '🌬', text: '¿Cómo está la calidad del aire?' },
];

function buildEmptyHTML() {
    const chips = SUGGESTED_PROMPTS.map((p, i) => `
        <button type="button" class="ai-chat-suggestion" data-suggestion-idx="${i}">
            <span class="ai-chat-suggestion-icon">${p.icon}</span>
            <span class="ai-chat-suggestion-text">${escapeHTML(p.text)}</span>
        </button>
    `).join('');
    return `
        <div class="ai-chat-empty">
            <strong>👋 ¡Hola!</strong> Soy Tenebris AI Sentinel.<br>
            Pregúntame algo o elige una sugerencia:
        </div>
        <div class="ai-chat-suggestions">${chips}</div>
    `;
}

function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let panelEl, fabEl, msgsEl, formEl, inputEl, sendBtn, statusEl;
let history = [];
let opened = false;
let busy = false;

export function initChat() {
    fabEl = document.getElementById('ai-chat-fab');
    panelEl = document.getElementById('ai-chat-panel');
    msgsEl = document.getElementById('ai-chat-messages');
    formEl = document.getElementById('ai-chat-form');
    inputEl = document.getElementById('ai-chat-input');
    sendBtn = document.getElementById('ai-chat-send');
    statusEl = document.getElementById('ai-chat-status');

    if (!fabEl || !panelEl) return;

    fabEl.addEventListener('click', toggle);
    document.getElementById('ai-chat-close')?.addEventListener('click', close);
    document.getElementById('ai-chat-clear')?.addEventListener('click', clearHistory);
    formEl?.addEventListener('submit', onSubmit);
    inputEl?.addEventListener('keydown', onKeyDown);
    inputEl?.addEventListener('input', autosize);

    // Delegado: click en cualquier chip de sugerencia inyecta la pregunta
    // y la envia inmediatamente (sin que el usuario tenga que dar Enter).
    msgsEl?.addEventListener('click', (e) => {
        const chip = e.target.closest('.ai-chat-suggestion');
        if (!chip || busy) return;
        const idx = Number(chip.dataset.suggestionIdx);
        const prompt = SUGGESTED_PROMPTS[idx];
        if (!prompt) return;
        if (inputEl) inputEl.value = prompt.text;
        formEl?.requestSubmit();
    });

    history = loadHistory();
    render();

    // Atajo C (solo en vista IA, no cuando hay otro modal abierto o el
    // usuario esta tipeando en un input)
    document.addEventListener('keydown', (e) => {
        if (e.target.matches('input, textarea, [contenteditable]')) return;
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        if (e.key === 'c' || e.key === 'C') {
            const aiVisible = !document.getElementById('view-ai')?.classList.contains('hidden');
            if (aiVisible) {
                e.preventDefault();
                toggle();
            }
        }
        if (e.key === 'Escape' && opened) close();
    });
}

export function toggleChat() { toggle(); }

function toggle() {
    if (opened) close(); else open();
}

function open() {
    panelEl.classList.remove('hidden');
    fabEl.classList.add('hidden');
    opened = true;
    setTimeout(() => inputEl?.focus(), 50);
    msgsEl.scrollTop = msgsEl.scrollHeight;
}

function close() {
    panelEl.classList.add('hidden');
    fabEl.classList.remove('hidden');
    opened = false;
}

function loadHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.slice(-MAX_HISTORY);
    } catch {
        return [];
    }
}

function saveHistory() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-MAX_HISTORY)));
    } catch {
        // localStorage lleno o deshabilitado: ignoramos
    }
}

function clearHistory() {
    if (history.length === 0) return;
    const confirmed = window.confirm(
        `¿Borrar los ${history.length} mensajes de esta conversación?\nEsta acción no se puede deshacer.`
    );
    if (!confirmed) return;
    history = [];
    saveHistory();
    render();
    setStatus('listo');
}

function setStatus(text, state) {
    if (!statusEl) return;
    statusEl.textContent = text;
    if (state) statusEl.dataset.state = state;
    else delete statusEl.dataset.state;
}

function render() {
    if (!msgsEl) return;
    if (history.length === 0) {
        msgsEl.innerHTML = buildEmptyHTML();
        return;
    }
    msgsEl.innerHTML = '';
    for (const m of history) appendMessage(m, false);
    msgsEl.scrollTop = msgsEl.scrollHeight;
}

function appendMessage(m, scroll = true) {
    const el = document.createElement('div');
    el.className = `ai-chat-msg ai-chat-msg-${m.role === 'user' ? 'user' : (m.role === 'error' ? 'error' : 'assistant')}`;
    el.innerHTML = renderMarkdownLite(m.content || '');

    // Charts inline: cada chart_spec se renderiza como un canvas ECharts
    if (m.charts && m.charts.length > 0) {
        for (const spec of m.charts) {
            try {
                renderChartInto(el, spec);
            } catch (e) {
                console.error('chart render fail', e);
            }
        }
    }

    if (m.tools && m.tools.length > 0) {
        const tools = document.createElement('div');
        tools.className = 'ai-chat-tools';
        tools.textContent = `🔧 ${m.tools.map((t) => t.name).join(', ')}`;
        el.appendChild(tools);
    }

    msgsEl.appendChild(el);
    if (scroll) msgsEl.scrollTop = msgsEl.scrollHeight;
}

// Crea un contenedor + instancia ECharts dentro del mensaje.
function renderChartInto(parentEl, spec) {
    if (!window.echarts) {
        const fallback = document.createElement('div');
        fallback.className = 'ai-chat-chart-error';
        fallback.textContent = '⚠ ECharts no cargado';
        parentEl.appendChild(fallback);
        return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'ai-chat-chart';
    parentEl.appendChild(wrap);

    // Construir option ECharts a partir del spec
    const series = (spec.series || []).map((s) => ({
        name: s.name,
        type: 'line',
        showSymbol: false,
        smooth: true,
        lineStyle: {
            color: s.color || '#E8B830',
            width: 2,
            type: s.dashed ? 'dashed' : 'solid',
        },
        itemStyle: { color: s.color || '#E8B830' },
        data: s.data || [],
    }));

    const markLine = spec.thresholds ? {
        symbol: 'none',
        lineStyle: { color: '#ef4444', type: 'dashed', width: 1, opacity: 0.7 },
        label: { show: true, formatter: '{b}', color: '#ef4444', fontSize: 10 },
        data: [
            { name: `min ${spec.thresholds.min}`, yAxis: spec.thresholds.min },
            { name: `max ${spec.thresholds.max}`, yAxis: spec.thresholds.max },
        ],
    } : undefined;
    if (markLine && series.length > 0) {
        series[0].markLine = markLine;
    }

    const isLight = document.querySelector('.ai-dashboard')?.dataset?.theme === 'light';
    const textColor = isLight ? '#1a2630' : '#E0E5E8';
    const axisColor = isLight ? '#94a3b8' : '#5b7888';

    const option = {
        title: spec.title ? {
            text: spec.title,
            left: 'center',
            textStyle: { color: textColor, fontSize: 12, fontWeight: 600 },
        } : undefined,
        animation: true,
        grid: { left: 50, right: 14, top: spec.title ? 38 : 14, bottom: 28 },
        legend: series.length > 1 ? {
            top: spec.title ? 22 : 4,
            textStyle: { color: textColor, fontSize: 10 },
            itemWidth: 14, itemHeight: 8,
        } : undefined,
        tooltip: {
            trigger: 'axis',
            valueFormatter: (v) => `${Number(v).toFixed(2)}${spec.unit || ''}`,
        },
        xAxis: {
            type: 'time',
            axisLabel: { color: axisColor, fontSize: 10, hideOverlap: true },
            axisLine: { lineStyle: { color: axisColor } },
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: {
                color: axisColor, fontSize: 10,
                formatter: (v) => `${v}${spec.unit || ''}`,
            },
            axisLine: { lineStyle: { color: axisColor } },
            splitLine: { lineStyle: { color: axisColor, opacity: 0.15 } },
        },
        series,
    };
    const chart = window.echarts.init(wrap, null, { renderer: 'canvas' });
    chart.setOption(option);
    // Re-size cuando cambia el panel
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(wrap);
}

// Markdown lite a mano: negritas **x**, codigo `x`, listas (- x), tablas
// pipe-style. Sin librerias externas. Escapamos HTML primero.
function renderMarkdownLite(text) {
    let s = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    // Codigo inline (antes de inlines que pudieran tocar `)
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Negritas
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italicas
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');

    // Procesado por bloques. Tablas y listas tienen su propia logica
    // multilinea; el resto se va a la salida con <br>.
    const lines = s.split('\n');
    const out = [];
    let inList = false;
    let i = 0;
    while (i < lines.length) {
        const ln = lines[i];

        // Detectar tabla: linea con pipes seguida de linea separadora |---|---|
        if (
            ln.includes('|') &&
            i + 1 < lines.length &&
            /^\s*\|?\s*[:-]+\s*(\|\s*[:-]+\s*)+\|?\s*$/.test(lines[i + 1])
        ) {
            if (inList) { out.push('</ul>'); inList = false; }
            const headerCells = splitPipeRow(ln);
            i += 2; // salta header y separador
            const bodyRows = [];
            while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
                bodyRows.push(splitPipeRow(lines[i]));
                i += 1;
            }
            out.push(renderTable(headerCells, bodyRows));
            continue;
        }

        // Listas (linea que empieza con "- " o "• ")
        const m = ln.match(/^\s*[-•]\s+(.*)$/);
        if (m) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push(`<li>${m[1]}</li>`);
            i += 1;
            continue;
        }

        if (inList) { out.push('</ul>'); inList = false; }
        out.push(ln);
        i += 1;
    }
    if (inList) out.push('</ul>');

    // Une con <br> sin meter <br> antes/despues de bloques (ul, table)
    return out.join('<br>')
        .replace(/<br><(ul|table)/g, '<$1')
        .replace(/<\/(ul|table)><br>/g, '</$1>');
}

function splitPipeRow(line) {
    // Trim y quita pipes de borde
    const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    return trimmed.split('|').map((c) => c.trim());
}

function renderTable(headers, rows) {
    const th = headers.map((h) => `<th>${h}</th>`).join('');
    const tbody = rows.map((r) => {
        // Si la fila tiene menos columnas que el header, rellena
        const cells = [];
        for (let i = 0; i < headers.length; i++) {
            cells.push(`<td>${r[i] ?? ''}</td>`);
        }
        return `<tr>${cells.join('')}</tr>`;
    }).join('');
    return `<table class="ai-chat-table"><thead><tr>${th}</tr></thead><tbody>${tbody}</tbody></table>`;
}

function autosize() {
    if (!inputEl) return;
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
}

function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        formEl?.requestSubmit();
    }
}

async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    const text = (inputEl?.value || '').trim();
    if (!text) return;

    const userMsg = { role: 'user', content: text };
    history.push(userMsg);
    saveHistory();
    if (msgsEl.querySelector('.ai-chat-empty') || msgsEl.querySelector('.ai-chat-suggestions')) {
        msgsEl.innerHTML = '';
    }
    appendMessage(userMsg);

    inputEl.value = '';
    autosize();
    setBusy(true);
    setStatus('pensando…', 'thinking');

    // Mostrar typing indicator
    const typingEl = document.createElement('div');
    typingEl.className = 'ai-chat-typing';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    msgsEl.appendChild(typingEl);
    msgsEl.scrollTop = msgsEl.scrollHeight;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
        // El backend ya inyecta su system prompt, asi que solo mandamos
        // los user/assistant turns previos (sin role 'error' que es UI-only)
        const apiHistory = history
            .filter((m) => m.role === 'user' || m.role === 'assistant')
            .slice(-MAX_HISTORY, -1); // todo menos el ultimo (que va como `message`)

        const r = await fetch(ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, history: apiHistory }),
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        typingEl.remove();

        const data = await r.json().catch(() => null);
        if (!r.ok || !data) {
            const errMsg = data?.error || `HTTP ${r.status}`;
            const err = { role: 'error', content: `⚠ ${errMsg}` };
            appendMessage(err);
            setStatus('error', 'error');
            return;
        }

        const reply = data.reply || '(sin respuesta)';
        const assistantMsg = {
            role: 'assistant',
            content: reply,
            tools: data.tool_calls || [],
            charts: data.charts || [],
        };
        history.push(assistantMsg);
        saveHistory();
        appendMessage(assistantMsg);
        setStatus('listo');
    } catch (err) {
        typingEl.remove();
        const isTimeout = err.name === 'AbortError';
        const errMsg = isTimeout ? '⏱ El agente tardó demasiado en responder. Intenta de nuevo.' : `⚠ ${err.message}`;
        appendMessage({ role: 'error', content: errMsg });
        setStatus('error', 'error');
    } finally {
        clearTimeout(timeoutId);
        setBusy(false);
    }
}

function setBusy(b) {
    busy = b;
    if (sendBtn) sendBtn.disabled = b;
    if (inputEl) inputEl.disabled = b;
    if (!b) inputEl?.focus();
}
