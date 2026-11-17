#!/usr/bin/env python3
import json
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = "PNinfa12345"
API = "https://sitiolaserena.onrender.com/api"

def curl(url):
    r = subprocess.run(["curl","-sS","--max-time","55","-H",f"x-admin-token: {TOKEN}",url], capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip() or "null")

def mins_to_hhmm(m):
    if m is None: return None
    h = m // 60
    mi = m % 60
    return f"{h:02d}:{mi:02d}"

def hhmm_to_min(s):
    h,m = map(int, s.split(':'))
    return h*60+m

def get_schedule(cfg, wden):
    # wden like mon/tue/wed/thu/fri/sat/sun
    sch = cfg.get('horario_semanal') or {}
    day = sch.get(wden) or {}
    o = day.get('open')
    c = day.get('close')
    if o is not None and c is not None:
        return int(o), int(c)
    # fallback open/close regular or weekend
    if wden in ('sat','sun'):
        return int(cfg.get('open_weekend_min') or cfg.get('open_regular_min') or 0), int(cfg.get('close_weekend_min') or cfg.get('close_regular_min') or 0)
    return int(cfg.get('open_regular_min') or 0), int(cfg.get('close_regular_min') or 0)

now = datetime.now(ZoneInfo("America/Santiago"))
wden = now.strftime("%a").lower()
# asegurar nombres cortos en inglés estándar (datetime.strftime da Mon/Tue/... => mon/tue)
print(f"Fecha/hora actual Chile: {now.isoformat()} | weekday short={wden}")
print()

for slug in ["la_serena", "coquimbo"]:
    nombre = "La Serena" if slug == "la_serena" else "Coquimbo"
    cfg = curl(f"{API}/config/{slug}")
    print("==", nombre, "==")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    openMin, closeMin = get_schedule(cfg, wden)
    cerrado = cfg.get('cerrado') is True
    origen = cfg.get('cerrado_origen')
    updated_at = cfg.get('cerrado_updated_at')
    print(f"Horario hoy {wden}: apertura={mins_to_hhmm(openMin)} ({openMin} min), cierre={mins_to_hhmm(closeMin)} ({closeMin} min)")
    currentMin = now.hour*60 + now.minute
    if not cerrado:
        if currentMin >= openMin and currentMin <= closeMin:
            openedMin = currentMin - openMin
            h = openedMin // 60
            m = openedMin % 60
            print(f"Estado: ABIERTO | Tiempo abierto: {h}h {m}m (desde {mins_to_hhmm(openMin)})")
        else:
            print("Estado: ABIERTO (según config) pero FUERA de horario -> parece inconsistente.")
    else:
        print(f"Estado: CERRADO (origen={origen}) | cerrado_updated_at={updated_at}")
        # Si está fuera de horario, calcular cuánto lleva cerrado desde el cierre de hoy.
        if currentMin > closeMin:
            closedMin = currentMin - closeMin
            h = closedMin // 60
            mm = closedMin % 60
            print(f"Tiempo cerrado: {h}h {mm}m (desde cierre {mins_to_hhmm(closeMin)})")
        elif currentMin < openMin:
            # Aún no abre hoy
            delta = openMin - currentMin
            h = delta // 60
            mm = delta % 60
            print(f"Aún no abre hoy | faltan {h}h {mm}m para abrir a las {mins_to_hhmm(openMin)}")
    print()
