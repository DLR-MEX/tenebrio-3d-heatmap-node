// Light/dark mode SOLO para la vista IA. La vista 3D de Danny queda en
// dark por diseño (los colores del heatmap dependen de fondo oscuro).
//
// El cambio se hace via data-theme="light"|"dark" en .ai-dashboard.
// Los overrides CSS viven en styles.css. Persiste en localStorage.

const STORAGE_KEY = 'ai-theme-ia';
const THEMES = ['dark', 'light'];

let toggleEl = null;
let dashEl = null;

export function initTheme() {
    dashEl = document.getElementById('view-ai');
    toggleEl = document.getElementById('ai-theme-toggle');
    if (!dashEl) return;

    const saved = readPref();
    apply(saved);

    if (toggleEl) {
        toggleEl.addEventListener('click', () => {
            const next = current() === 'light' ? 'dark' : 'light';
            apply(next);
            writePref(next);
        });
    }
}

function current() {
    return dashEl?.dataset.theme === 'light' ? 'light' : 'dark';
}

function apply(theme) {
    if (!dashEl) return;
    if (!THEMES.includes(theme)) theme = 'dark';
    dashEl.dataset.theme = theme;
    if (toggleEl) {
        toggleEl.textContent = theme === 'light' ? '🌙' : '☀';
        toggleEl.title = theme === 'light'
            ? 'Cambiar a modo oscuro'
            : 'Cambiar a modo claro';
        toggleEl.setAttribute('aria-pressed', String(theme === 'light'));
    }
}

function readPref() {
    try {
        const v = localStorage.getItem(STORAGE_KEY);
        return THEMES.includes(v) ? v : 'dark';
    } catch {
        return 'dark';
    }
}

function writePref(theme) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch {}
}
