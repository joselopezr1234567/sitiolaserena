#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

TOKEN = "PNinfa12345"
API = "https://sitiolaserena.onrender.com/api"

def norm(s):
    return (s or "").strip().lower()

def curl_json(url, headers):
    for _ in range(2):
        try:
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "50", "-H", f"x-admin-token: {TOKEN}", url],
                capture_output=True, text=True, check=True
            )
            txt = r.stdout.strip()
            if not txt:
                continue
            return json.loads(txt)
        except Exception as e:
            err = e
            continue
    raise RuntimeError(f"curl_json failed for {url}: {err}")

print("== BUSQUEDA DE PEDIDOS DE Camilo Medina ==")
print()

print("[1] Buscar en /api/admin/pedidos?sucursal=La Serena (incluye cancelado/pendiente)")
pedidos_activos = curl_json(f"{API}/admin/pedidos?sucursal=La%20Serena", {})
hits_activos = [r for r in pedidos_activos if 'camilo' in norm(r.get('usuario_nombre',''))]
print(f"Total retornados por el endpoint activos: {len(pedidos_activos)}")
print(f"Hits por nombre 'Camilo' en pedidos activos: {len(hits_activos)}")
for r in hits_activos:
    print(json.dumps(r, ensure_ascii=False))
print()

print("[2] Buscar por cierre en varios días (solo estado pagado/listo)")
dias = [
    "2026-09-09","2026-09-08","2026-09-07","2026-09-06","2026-09-05",
    "2026-09-04","2026-09-03","2026-09-02","2026-09-01","2026-08-31",
    "2026-08-30","2026-08-29","2026-08-28","2026-08-27","2026-08-26",
    "2026-08-25","2026-08-24","2026-08-23","2026-08-22","2026-08-21",
    "2026-08-20","2026-08-19","2026-08-18","2026-08-17","2026-08-16",
    "2026-08-15","2026-08-14","2026-08-13","2026-08-12","2026-08-11",
    "2026-08-10","2026-08-09","2026-08-08","2026-08-07","2026-08-06",
    "2026-08-05","2026-08-04","2026-08-03","2026-08-02","2026-08-01",
]
hits_cierre = []
for d in dias:
    try:
        data = curl_json(f"{API}/admin/cierre?sucursal=La%20Serena&fecha={d}", {})
    except Exception:
        continue
    rows = data.get('pedidos', [])
    if not rows:
        continue
    for r in rows:
        if 'camilo' in norm(r.get('usuario_nombre','')):
            hits_cierre.append(r)
print(f"Hits en cierres (pagado/listo): {len(hits_cierre)}")
for r in hits_cierre:
    print(json.dumps(r, ensure_ascii=False))
print()

print("[3] Resumen consolidado Camilo")
todos = hits_activos + hits_cierre
# dedupe por id
seen = set()
uniq = []
for r in todos:
    pid = r.get('id')
    if pid in seen: continue
    seen.add(pid)
    uniq.append(r)

# Ordenar por fecha descendente
def fecha_key(r):
    return r.get('fecha_local') or r.get('fecha') or ''

uniq.sort(key=fecha_key, reverse=True)
print(f"Total pedidos únicos de Camilo (encontrados en endpoints disponibles): {len(uniq)}")
for r in uniq:
    print(json.dumps(r, ensure_ascii=False))
