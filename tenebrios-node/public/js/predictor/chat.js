// Widget de chat IA: boton flotante + panel deslizable.
// Usa /api/predictor/agent/chat via Express -> sidecar Python.
// Historial vive en localStorage (max 30 mensajes); cada turno
// reenvia el history al backend (el LLM no tiene memoria propia).

const ENDPOINT = '/api/predictor/agent/chat';
const STORAGE_KEY = 'ai-chat-history-v1';
const MAX_HISTORY = 30;
const REQUEST_TIMEOUT_MS = 35000;

const EMPTY_HTML = `
    <div class="ai-chat-empty">
        <strong>👋 ¡Hola!</strong> Soy Tenebris AI Sentinel.<br>
        Pregúntame en español sobre el cuarto:<br>
        <em>¿cómo está la temperatura?</em><br>
        <em>¿hubo anomalías hoy?</em><br>
        <em>promedio de t1 en las últimas 6 horas</em>
    </div>
`;

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
    history = [];
    saveHistory();
    render();
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
        msgsEl.innerHTML = EMPTY_HTML;
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

    if (m.tools && m.tools.length > 0) {
        const tools = document.createElement('div');
        tools.className = 'ai-chat-tools';
        tools.textContent = `🔧 ${m.tools.map((t) => t.name).join(', ')}`;
        el.appendChild(tools);
    }

    msgsEl.appendChild(el);
    if (scroll) msgsEl.scrollTop = msgsEl.scrollHeight;
}

// Markdown lite a mano (negritas **x**, codigo `x`, listas - x).
// Sin librerias externas. Escapamos HTML primero.
function renderMarkdownLite(text) {
    let s = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    // Codigo inline
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Negritas
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italicas
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    // Listas (linea que empieza con "- " o "• ")
    const lines = s.split('\n');
    let inList = false;
    const out = [];
    for (const ln of lines) {
        const m = ln.match(/^\s*[-•]\s+(.*)$/);
        if (m) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push(`<li>${m[1]}</li>`);
        } else {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push(ln);
        }
    }
    if (inList) out.push('</ul>');
    return out.join('<br>').replace(/<\/ul><br>/g, '</ul>').replace(/<br><ul>/g, '<ul>');
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
    if (msgsEl.querySelector('.ai-chat-empty')) msgsEl.innerHTML = '';
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
