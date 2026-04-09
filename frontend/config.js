window.APP_CONFIG = {
    API_BASE_URL: (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:3000'
        : 'https://sitiolaserena.onrender.com'
};

(function () {
    const TZ_CHILE = 'America/Santiago';
    const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: TZ_CHILE,
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });

    function getChileParts() {
        const parts = fmt.formatToParts(new Date());
        const out = {};
        for (const p of parts) out[p.type] = p.value;
        const weekday = out.weekday;
        const hour = parseInt(out.hour, 10);
        const minute = parseInt(out.minute, 10);
        return { weekday, minutes: hour * 60 + minute };
    }

    function isOpenNowFromConfig(cfg) {
        const { weekday, minutes } = getChileParts();
        if (!cfg) return { open: true };
        const dayKey = weekday === 'Mon' ? 'mon'
            : weekday === 'Tue' ? 'tue'
            : weekday === 'Wed' ? 'wed'
            : weekday === 'Thu' ? 'thu'
            : weekday === 'Fri' ? 'fri'
            : weekday === 'Sat' ? 'sat'
            : weekday === 'Sun' ? 'sun'
            : null;
        if (dayKey && cfg.horario_semanal && typeof cfg.horario_semanal === 'object' && cfg.horario_semanal[dayKey]) {
            const d = cfg.horario_semanal[dayKey];
            const openMin = Number(d.open);
            const closeMin = Number(d.close);
            if (!Number.isFinite(openMin) || !Number.isFinite(closeMin)) return { open: false };
            return { open: minutes >= openMin && minutes <= closeMin };
        }
        const openReg = Number(cfg.open_regular_min ?? 810);
        const closeReg = Number(cfg.close_regular_min ?? 1375);
        const openWe = Number(cfg.open_weekend_min ?? 810);
        const closeWe = Number(cfg.close_weekend_min ?? 1420);
        const openMin = (weekday === 'Fri' || weekday === 'Sat') ? openWe : openReg;
        const closeMin = (weekday === 'Fri' || weekday === 'Sat') ? closeWe : closeReg;
        const open = minutes >= openMin && minutes <= closeMin;
        return { open };
    }

    function ensureOverlay() {
        let overlay = document.getElementById('closed-overlay');
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.id = 'closed-overlay';
        overlay.style.position = 'fixed';
        overlay.style.inset = '0';
        overlay.style.background = 'rgba(0, 0, 0, 0.9)';
        overlay.style.zIndex = '10000';
        overlay.style.display = 'none';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.textAlign = 'center';
        overlay.style.padding = '24px';
        overlay.innerHTML = `
            <div style="max-width:640px">
                <div style="color:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:1.35rem;font-weight:700;line-height:1.4">
                    Estimad@ cliente en este momento nos encontramos cerrado
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    async function refresh() {
        let open = true;
        try {
            const baseUrl = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) ? window.APP_CONFIG.API_BASE_URL : 'http://localhost:3000';
            const path = (location.pathname || '').toLowerCase();
            let suc = null;
            if (path.includes('menulaserena')) suc = 'la_serena';
            else if (path.includes('menucoquimbo')) suc = 'coquimbo';
            if (suc) {
                const res = await fetch(`${baseUrl}/api/config/${suc}`);
                if (res.ok) {
                    const cfg = await res.json();
                    open = isOpenNowFromConfig(cfg).open;
                    if (cfg && cfg.cerrado === true) {
                        open = false;
                    }
                }
            }
        } catch {}
        window.APP_OPEN = open;
        const overlay = ensureOverlay();
        overlay.style.display = open ? 'none' : 'flex';
        document.documentElement.style.overflow = open ? '' : 'hidden';
        document.body.style.overflow = open ? '' : 'hidden';
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            refresh();
            setInterval(refresh, 30000);
        });
    } else {
        refresh();
        setInterval(refresh, 30000);
    }
})();
