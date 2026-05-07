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
    if (enabled) enabled.checked = Boolean(data.enabled);
    if (chat) chat.value = data.chat_id || '';
    if (cooldown) cooldown.value = Number.isFinite(data.cooldown_sec) ? data.cooldown_sec : 300;

    const stateBadge = document.getElementById('ai-cfg-state');
    if (stateBadge) {
        stateBadge.textContent = data.enabled ? 'ACTIVO' : 'INACTIVO';
        stateBadge.dataset.state = data.enabled ? 'on' : 'off';
    }
}

async function onSave(e) {
    e.preventDefault();
    const chat = (document.getElementById('ai-cfg-chatid')?.value || '').trim();
    const enabled = document.getElementById('ai-cfg-enabled')?.checked || false;
    const cooldownStr = document.getElementById('ai-cfg-cooldown')?.value || '300';
    const cooldown = parseFloat(cooldownStr);

    if (chat && !/^-?\d+$/.test(chat)) {
        setMessage('chat_id debe ser un numero entero (positivo o negativo).', 'error');
        return;
    }
    if (!Number.isFinite(cooldown) || cooldown < 30 || cooldown > 3600) {
        setMessage('cooldown_sec debe estar entre 30 y 3600.', 'error');
        return;
    }

    setBusy(true);
    setMessage('Guardando...', null);
    try {
        const r = await fetch(API.post, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chat, enabled, cooldown_sec: cooldown }),
        });
        const data = await r.json();
        if (!r.ok) {
            throw new Error(data.error || `HTTP ${r.status}`);
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
        setMessage(`Error: ${err.message}`, 'error');
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
