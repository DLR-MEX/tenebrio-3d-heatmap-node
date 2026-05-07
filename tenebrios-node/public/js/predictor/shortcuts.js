// Atajos de teclado para la app. Mapeo:
//   V → toggle vista 3D ↔ IA
//   T → abrir modal Telegram (solo si vista IA esta visible)
//   M → mute/unmute sonido alerta
//   D → demo mode (oculta header global para presentaciones limpias)
//   ? → mostrar/ocultar cheat sheet con esta lista
//   Escape → ya lo usa Danny (immersive mode) y el modal Telegram, no se toca
//
// Reglas:
//   - No dispara si el foco esta en un input/textarea/select (typeo libre)
//   - No dispara si hay un modal abierto (excepto el cheat sheet con ?)
//   - El cheat sheet se cierra con ? o Escape

const KEYS = {
    'v': () => clickViewToggle(),
    't': () => openTelegramModalIfPossible(),
    'm': () => clickSoundToggle(),
    'd': () => toggleDemoMode(),
    '?': () => toggleCheatSheet(),
};

let cheatEl = null;

export function initShortcuts() {
    cheatEl = document.getElementById('ai-shortcuts-modal');
    if (cheatEl) {
        cheatEl.addEventListener('click', (e) => {
            if (e.target === cheatEl) toggleCheatSheet();
        });
        document.getElementById('ai-shortcuts-close')?.addEventListener('click', toggleCheatSheet);
    }

    document.addEventListener('keydown', (e) => {
        // Si esta tipeando en un input/textarea/select/contenteditable, NO interceptamos
        const tag = (e.target?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
        if (e.target?.isContentEditable) return;
        // Si hay modificadores (Ctrl/Cmd/Alt), dejamos pasar — son atajos del browser
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        // Cheat sheet abierto: solo ? y Escape lo cierran
        if (cheatEl && !cheatEl.classList.contains('hidden')) {
            if (e.key === '?' || e.key === 'Escape') {
                e.preventDefault();
                toggleCheatSheet();
            }
            return;
        }

        // Si hay otro modal abierto (telegram), no interceptamos para no chocar
        const telegramOpen = document.getElementById('ai-cfg-modal')
            && !document.getElementById('ai-cfg-modal').classList.contains('hidden');
        if (telegramOpen) return;

        const handler = KEYS[e.key.toLowerCase()] || KEYS[e.key];
        if (handler) {
            e.preventDefault();
            handler();
        }
    });
}

// ---------- handlers ----------

function clickViewToggle() {
    // Buscar el boton de la vista que NO esta activa y hacerle click
    const inactive = document.querySelector('.view-toggle button:not(.active)');
    if (inactive) inactive.click();
}

function openTelegramModalIfPossible() {
    // Solo abre si la vista IA esta visible (cuando estamos en 3D, no tiene sentido)
    const aiVisible = !document.getElementById('view-ai')?.classList.contains('hidden');
    if (!aiVisible) return;
    document.getElementById('ai-cfg-trigger')?.click();
}

function clickSoundToggle() {
    document.getElementById('ai-sound-toggle')?.click();
}

function toggleDemoMode() {
    // Oculta el header con logos para presentaciones / fotos limpias
    document.body.classList.toggle('demo-mode');
    // Forzar resize por si afecta layout
    setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
}

function toggleCheatSheet() {
    if (!cheatEl) return;
    cheatEl.classList.toggle('hidden');
}
