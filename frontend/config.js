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

    function isOpenNow() {
        const { weekday, minutes } = getChileParts();
        const start = 13 * 60 + 30;
        const end = (weekday === 'Fri' || weekday === 'Sat') ? (23 * 60 + 40) : (22 * 60 + 55);
        const open = minutes >= start && minutes <= end;
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

    function refresh() {
        const { open } = isOpenNow();
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
