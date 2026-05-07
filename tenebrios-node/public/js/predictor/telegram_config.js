// Modal de configuracion Telegram (chat_id / enabled / cooldown / test).
// Se abre con el icono de engrane en el header de la vista IA.
//
// Diseño de seguridad:
//   - Nunca pedimos ni mostramos el bot_token.
//   - El backend devuelve token_configured: bool — si false, mostramos
//     un aviso de que hay que poner el token en .env.
//   - Validacion clientside basica (numero, rango cooldown), validacion
//     real en backend.

const API = {
    get: '/api/predictor/telegram',
    post: '/api/predictor/telegram',
    test: '/api/predictor/telegram/test',
};

let modal = null;
let opened = false;

export function initTelegramConfig() {
    const trigger = document.getElementById('ai-cfg-trigger');
    if (!trigger) return;
    trigger.addEventListener('click', openModal);

    modal = document.getElementById('ai-cfg-modal');
    if (!modal) return;

    modal.addEventListener('click', (e) => {
        // click fuera del card -> cerrar
        if (e.target === modal) closeModal();
    });
    document.getElementById('ai-cfg-close')?.addEventListener('click', closeModal);
    document.getElementById('ai-cfg-cancel')?.addEventListener('click', closeModal);
    document.getElementById('ai-cfg-form')?.addEventListener('submit', onSave);
    document.getElementById('ai-cfg-test')?.addEventListener('click', onTest);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && opened) closeModal();
    });

    // Live sanitize del chat_id: si el usuario pega "Id: -1001234567890",
    // o "@userinfobot dice 123456789", extraemos automaticamente el numero.
    const chatInput = document.getElementById('ai-cfg-chatid');
    if (chatInput) {
        chatInput.addEventListener('input', () => {
            const cleaned = sanitizeChatId(chatInput.value);
            const preview = document.getElementById('ai-cfg-chatid-preview');
            if (preview) {
                if (cleaned && cleaned !== chatInput.value.trim()) {
                    preview.textContent = `Se guardará como: ${cleaned}`;
                    preview.classList.add('visible');
                } else {
                    preview.classList.remove('visible');
                    preview.textContent = '';
                }
            }
        });
    }
}

// Extrae chat_id valido (entero opt. negativo) del input. Tolera prefijos
// como "Id:", "id ", "chat_id =", espacios, separadores de miles, etc.
// Si no encuentra un numero valido, devuelve ''.
function sanitizeChatId(raw) {
    if (!raw) return '';
    // Buscamos el primer "candidato": opcional minus, seguido de digitos.
    // Permitimos separadores comunes (`,` `.` ` `) entre digitos y los borramos.
    const match = String(raw).match(/-?[\d][\d\s.,_]*/);
    if (!match) return '';
    // Quitamos los separadores no-digito (excepto el minus inicial)
    let s = match[0].replace(/[\s.,_]/g, '');
    // Aseguramos que el minus quede solo al inicio
    const negative = s.startsWith('-');
    s = s.replace(/-/g, '');
    if (negative) s = '-' + s;
    return s;
}

async function openModal() {
    if (!modal) return;
    modal.classList.remove('hidden');
    opened = true;
    setMessage('', null);
    await loadCurrent();
}

function closeModal() {
    if (!modal) return;
    modal.classList.add('hidden');
    opened = false;
}

async function loadCurrent() {
    setBusy(true);
    try {
        const r = await fetch(API.get, { cache: 'no-store' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        applyToForm(data);
    } catch (err) {
        setMessage(`No se pudo cargar la configuracion: ${err.message}`, 'error');
    } finally {
        setBusy(false);
    }
}

function applyToForm(data) {
    const tokenWarn = document.getElementById('ai-cfg-token-warn');
    if (tokenWarn) {
        tokenWarn.classList.toggle('hidden', Boolean(data.token_configured));
    }
    const enabled = document.getElementById('ai-cfg-enabled');
    const chat = document.getElementById('ai-cfg-chatid');
    const cooldown = document.getElementById('ai-cfg-cooldown');
    const listener = document.getElementById('ai-cfg-listener');
    const listenerHint = document.getElementById('ai-cfg-listener-hint');
    if (enabled) enabled.checked = Boolean(data.enabled);
    if (chat) chat.value = data.chat_id || '';
    if (cooldown) cooldown.value = Number.isFinite(data.cooldown_sec) ? data.cooldown_sec : 300;
    if (listener) {
        listener.checked = Boolean(data.listener_enabled);
        // Si el agente IA no esta listo (sin API key), deshabilitamos el toggle
        const available = Boolean(data.listener_available);
        listener.disabled = !available;
        if (listenerHint) {
            listenerHint.textContent = available
                ? 'Si activas esto, el bot responde mensajes que le mandes en lenguaje natural usando la API de Ollama Cloud. Consume tokens del LLM.'
                : 'Agente IA no configurado (falta OLLAMA_API_KEY en .env del sidecar). Configurar y reiniciar para habilitar.';
        }
    }

    const stateBadge = document.getElementById('ai-cfg-state');
    if (stateBadge) {
        stateBadge.textContent = data.enabled ? 'ACTIVO' : 'INACTIVO';
        stateBadge.dataset.state = data.enabled ? 'on' : 'off';
    }
}

async function onSave(e) {
    e.preventDefault();
    const chatRaw = (document.getElementById('ai-cfg-chatid')?.value || '').trim();
    // Sanitize: extrae numero del input aunque venga con "Id:", separadores, etc.
    const chat = sanitizeChatId(chatRaw);
    // Reflejar el valor sanitizado en el input para que el usuario vea exactamente
    // que se guardo (en caso de que pegara basura)
    if (chatRaw && chat) {
        const input = document.getElementById('ai-cfg-chatid');
        if (input) input.value = chat;
    }

    const enabled = document.getElementById('ai-cfg-enabled')?.checked || false;
    const listenerEnabled = document.getElementById('ai-cfg-listener')?.checked || false;
    const cooldownStr = document.getElementById('ai-cfg-cooldown')?.value || '300';
    const cooldown = parseFloat(cooldownStr);

    // Validacion: si el usuario escribio algo pero sanitize devolvio vacio, error
    if (chatRaw && !chat) {
        setMessage(`No se pudo extraer un chat_id numerico de "${chatRaw}". Esperado: solo digitos, opcional minus inicial. Ej. 123456789 o -1001234567890.`, 'error');
        return;
    }
    if (!Number.isFinite(cooldown) || cooldown < 30 || cooldown > 3600) {
        setMessage('cooldown_sec debe estar entre 30 y 3600.', 'error');
        return;
    }

    setBusy(true);
    setMessage('Guardando...', null);

    const payload = { chat_id: chat, enabled, cooldown_sec: cooldown, listener_enabled: listenerEnabled };
    // Diagnostico en consola para que F12 muestre exactamente que mandamos
    console.log('[telegram-cfg] POST', API.post, payload);

    try {
        const r = await fetch(API.post, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        // Leemos el body como texto primero, asi vemos contenido aunque no sea JSON
        const text = await r.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch { /* respuesta no es JSON */ }
        console.log('[telegram-cfg] response', r.status, data ?? text);

        if (!r.ok) {
            const apiErr = data?.error || data?.detail || (text ? text.slice(0, 200) : '');
            throw new Error(apiErr ? `${apiErr} (HTTP ${r.status})` : `HTTP ${r.status}`);
        }
        if (!data) {
            throw new Error('Respuesta vacia del servidor');
        }
        applyToForm(data);
        // Si el usuario marco enabled pero no hay token o chat_id, el backend
        // lo deja en false automaticamente. Avisamos.
        if (enabled && !data.enabled) {
            setMessage('Guardado, pero sigue INACTIVO (revisa que el token este en .env y que el chat_id no este vacio).', 'warn');
        } else {
            setMessage(data.enabled ? 'Configuracion guardada. Notificaciones ACTIVAS.' : 'Configuracion guardada (notificaciones inactivas).', 'ok');
        }
    } catch (err) {
        setMessage(`Error al guardar: ${err.message}`, 'error');
    } finally {
        setBusy(false);
    }
}

async function onTest() {
    setBusy(true);
    setMessage('Mandando mensaje de prueba...', null);
    try {
        const r = await fetch(API.test, { method: 'POST' });
        const data = await r.json();
        if (!r.ok || !data.sent) {
            throw new Error(data.error || `HTTP ${r.status}`);
        }
        setMessage('✅ Mensaje enviado. Revisa el chat en Telegram.', 'ok');
    } catch (err) {
        setMessage(`No se pudo enviar: ${err.message}`, 'error');
    } finally {
        setBusy(false);
    }
}

function setBusy(busy) {
    const form = document.getElementById('ai-cfg-form');
    if (form) form.classList.toggle('busy', busy);
    document.querySelectorAll('#ai-cfg-modal button, #ai-cfg-modal input')
        .forEach((el) => { el.disabled = busy; });
}

function setMessage(text, kind) {
    const msg = document.getElementById('ai-cfg-msg');
    if (!msg) return;
    msg.textContent = text || '';
    msg.classList.remove('ok', 'error', 'warn');
    if (kind) msg.classList.add(kind);
}
