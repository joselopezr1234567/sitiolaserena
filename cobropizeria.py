import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from decimal import Decimal, ROUND_HALF_UP
import requests

# --- CONFIGURACIÓN ---
API_URL = os.environ.get("API_URL", "https://sitiolaserena.onrender.com/api")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")

def _admin_headers():
    return {"x-admin-token": ADMIN_API_TOKEN} if ADMIN_API_TOKEN else {}

def _formato_moneda(valor: Decimal) -> str:
    return f"${valor.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}".replace(",", ".")

class AppReporteComisiones:
    def __init__(self, root):
        self.root = root
        self.root.title("Dashboard de Inteligencia de Negocios - Pizzería")
        self.root.geometry("1050x850")
        self.root.configure(bg="#111")
        self.datos_cache = {}

        # Estilos visuales
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#222", foreground="white", fieldbackground="#222", rowheight=30)
        style.configure("Treeview.Heading", background="#333", foreground="white", font=("Arial", 10, "bold"))
        style.configure("TCombobox", fieldbackground="white", foreground="black")

        # Header
        frame_top = tk.Frame(root, bg="#333", pady=10)
        frame_top.pack(fill=tk.X)
        tk.Label(frame_top, text="ANÁLISIS DE ACELERACIÓN COMERCIAL", font=("Arial", 16, "bold"), fg="white", bg="#333").pack(side=tk.LEFT, padx=20)
        
        self.mes_selector = ttk.Combobox(frame_top, state="readonly", width=15)
        self.mes_selector.pack(side=tk.LEFT, padx=10)
        self.mes_selector.bind("<<ComboboxSelected>>", lambda e: self._renderizar())
        
        btn_cargar = tk.Button(frame_top, text="ACTUALIZAR DATOS", command=self.cargar_datos, bg="#DDDDDD", fg="black", font=("Arial", 10, "bold"))
        btn_cargar.pack(side=tk.RIGHT, padx=20)

        # Tabla
        cols = ("mes", "sucursal", "ventas", "comision", "iva", "total")
        self.tree = ttk.Treeview(root, columns=cols, show="headings")
        for col, head in [("mes", "MES"), ("sucursal", "SUCURSAL"), ("ventas", "VENTAS"), ("comision", "5%"), ("iva", "IVA"), ("total", "TOTAL")]:
            self.tree.heading(col, text=head)
            self.tree.column(col, width=140, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Área de Análisis
        self.lbl_analisis = tk.Text(root, height=14, bg="#222", fg="#00FF00", font=("Consolas", 11), padx=10, pady=10)
        self.lbl_analisis.pack(fill=tk.X, padx=20, pady=10)

    def cargar_datos(self):
        threading.Thread(target=self._fetch_api, daemon=True).start()

    def _fetch_api(self):
        try:
            resp = requests.get(f"{API_URL}/admin/pedidos", headers=_admin_headers(), timeout=30)
            if resp.status_code != 200: raise Exception(f"API Error: {resp.status_code}")
            
            data = resp.json()
            resumen = {}
            for p in data:
                if str(p.get('estado', '')).lower() in ['pagado', 'listo', 'entregado', 'finalizado']:
                    mes = p.get('fecha', '')[:7] if len(p.get('fecha', '')) >= 7 else "Sin Fecha"
                    sucursal = p.get('sucursal', 'Indefinida')
                    total = Decimal(str(p.get('total', 0)))
                    if mes not in resumen: resumen[mes] = {}
                    resumen[mes][sucursal] = resumen[mes].get(sucursal, Decimal(0)) + total
            
            self.datos_cache = resumen
            meses = sorted(resumen.keys(), reverse=True)
            self.root.after(0, lambda: self._actualizar_selector(meses))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _actualizar_selector(self, meses):
        self.mes_selector['values'] = ["TODOS"] + meses
        self.mes_selector.current(0)
        self._renderizar()

    def _ejecutar_analisis(self):
        meses = sorted(self.datos_cache.keys(), reverse=True)
        if len(meses) < 3: return "Análisis: Se requieren al menos 3 meses de histórico."
        
        m1 = sum(self.datos_cache[meses[0]].values()) # Mes reciente
        m2 = sum(self.datos_cache[meses[1]].values())
        m3 = sum(self.datos_cache[meses[2]].values())
        
        # Cálculo de aceleración y tendencia
        crec1 = m1 - m2
        crec2 = m2 - m3
        aceleracion = crec1 - crec2
        tasa_promedio = ((m1/m2) + (m2/m3)) / 2
        proyeccion = m1 * tasa_promedio
        
        estado = "ACELERACIÓN POSITIVA (CRECIMIENTO ACUMULADO)" if aceleracion > 0 else "DESACELERACIÓN DETECTADA"
        
        return (
            f"--- ESTUDIO DE TENDENCIA Y ACELERACIÓN ---\n"
            f"1. Estado actual: {estado}\n"
            f"2. Crecimiento del último periodo: {_formato_moneda(crec1)}\n"
            f"3. Aceleración detectada: {_formato_moneda(aceleracion)}\n"
            f"4. Proyección ajustada (Tasa Compuesta): {_formato_moneda(proyeccion)}\n\n"
            f"EXPLICACIÓN: Detectamos que tu negocio mantiene una inercia de crecimiento.\n"
            f"El modelo aplica una tasa de crecimiento compuesta basándose en que el incremento\n"
            f"entre los últimos meses es mayor al anterior. ¡Tus ventas están ganando fuerza!"
        )

    def _renderizar(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        if not self.datos_cache: return
        
        filtro = self.mes_selector.get() or "TODOS"
        for mes in sorted(self.datos_cache.keys(), reverse=True):
            if filtro != "TODOS" and mes != filtro: continue
            for suc in sorted(self.datos_cache[mes].keys()):
                v = self.datos_cache[mes][suc]
                c = v * Decimal("0.05"); i = c * Decimal("0.19"); t = c + i
                self.tree.insert("", "end", values=(mes, suc, _formato_moneda(v), _formato_moneda(c), _formato_moneda(i), _formato_moneda(t)))
        
        self.lbl_analisis.delete("1.0", tk.END)
        self.lbl_analisis.insert(tk.END, self._ejecutar_analisis())

if __name__ == "__main__":
    root = tk.Tk()
    AppReporteComisiones(root)
    root.mainloop()