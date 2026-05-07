// Indicadores de alerta visibles desde lejos:
//   1) Banner por seccion (TEMP / HUM) listando sensores en peligro con valor
//   2) Contador en el boton "🤖 IA +3min" del header global, asi se ve el
//      problema incluso cuando el usuario esta mirando la vista 3D
//
// Uso:
//   updateAlertIndicators('TEMP', { vars, current, predicted, alerts })
//
// Internamente mantenemos el estado por grupo y luego recomputamos el total
// para el contador del boton.

const GROUP_LABELS = { TEMP: 'temperatura', HUM: 'humedad' };
const GROUP_UNITS  = { TEMP: '°C',          HUM: '%' };

// Numeros agregados por grupo (para el contador del boton)
const groupCounts = { TEMP: 0, HUM: 0 };

export function updateAlertIndicators(group, payload) {
    if (!payload || !payload.vars || !payload.alerts) return;

    const dangerSensors = [];   // current = abnormal
    const warnSensors   = [];   // current ok, predicho abnormal
    const unit = GROUP_UNITS[group] || '';

    for (const v of payload.vars) {
        const a = payload.alerts[v];
        if (!a) continue;
        if (a.current === 'abnormal') {
            dangerSensors.push({ name: v, value: payload.current?.[v] });
        } else if (a.predicted === 'abnormal') {
            warnSensors.push({ name: v, value: payload.predicted?.[v] });
        }
    }

    renderBanner(group, dangerSensors, warnSensors, unit);
    groupCounts[group] = dangerSensors.length + warnSensors.length;
    renderToggleBadge();
}

// ---------- banner ----------

function renderBanner(group, dangers, warns, unit) {
    const banner = document.getElementById(`ai-banner-${group.toLowerCase()}`);
    if (!banner) return;

    if (dangers.length === 0 && warns.length === 0) {
        banner.classList.remove('visible', 'danger', 'warn');
        banner.textContent = '';
        return;
    }

    // Texto compacto: "🚨 2 en peligro: t1 32.5°C, t3 31.8°C  ⚠ 1 anticipada: h2 60.2%"
    const parts = [];
    if (dangers.length) {
        const list = dangers.map((s) => `${s.name} ${fmt(s.value, unit)}`).join(', ');
        parts.push(`🚨 ${dangers.length} en peligro: ${list}`);
    }
    if (warns.length) {
        const list = warns.map((s) => `${s.name} ${fmt(s.value, unit)}`).join(', ');
        parts.push(`⚠ ${warns.length} anticipada${warns.length === 1 ? '' : 's'}: ${list}`);
    }

    banner.textContent = parts.join('   ·   ');
    banner.classList.add('visible');
    banner.classList.toggle('danger', dangers.length > 0);
    banner.classList.toggle('warn', dangers.length === 0 && warns.length > 0);
}

function fmt(n, unit) {
    if (!Number.isFinite(n)) return '?';
    return `${n.toFixed(1)}${unit}`;
}

// ---------- counter en botón vista IA ----------

function renderToggleBadge() {
    const btn = document.getElementById('btn-view-ai');
    if (!btn) return;
    const total = groupCounts.TEMP + groupCounts.HUM;

    // Buscar/crear span badge dentro del boton (sin sobrescribir su texto)
    let badge = btn.querySelector('.ai-toggle-badge');
    if (total === 0) {
        if (badge) badge.remove();
        btn.classList.remove('has-alerts');
        return;
    }
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'ai-toggle-badge';
        btn.appendChild(badge);
    }
    badge.textContent = String(total);
    btn.classList.add('has-alerts');
}
