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
            # Guardamos ventas por día para comparación precisa
            self.ventas_diarias = {} # { '2024-06-15': Decimal(100) }

            for p in data:
                if str(p.get('estado', '')).lower() in ['pagado', 'listo', 'entregado', 'finalizado']:
                    fecha_completa = p.get('fecha', '') # 'YYYY-MM-DD HH:MM:SS'
                    if len(fecha_completa) < 10: continue

                    mes = fecha_completa[:7]
                    dia_completo = fecha_completa[:10]
                    sucursal = p.get('sucursal', 'Indefinida')
                    total = Decimal(str(p.get('total', 0)))

                    # Resumen mensual (para la tabla)
                    if mes not in resumen: resumen[mes] = {}
                    resumen[mes][sucursal] = resumen[mes].get(sucursal, Decimal(0)) + total

                    # Registro diario (para el análisis) - SUMA TODAS LAS SUCURSALES
                    self.ventas_diarias[dia_completo] = self.ventas_diarias.get(dia_completo, Decimal(0)) + total
            
            self.datos_cache = resumen
            meses = sorted(resumen.keys(), reverse=True)
            self.root.after(0, lambda: self._actualizar_selector(meses))
        except Exception as e:
    # 1. Convertimos el error a texto de inmediato mientras 'e' existe
            mensaje_error = str(e) 
    
    # 2. Le pasamos el texto ya listo a tkinter sin usar lambda
            self.root.after(0, lambda: messagebox.showerror("Error", mensaje_error))



    def _actualizar_selector(self, meses):
        self.mes_selector['values'] = ["TODOS"] + meses
        self.mes_selector.current(0)
        self._renderizar()

    def _ejecutar_analisis(self):
        if not hasattr(self, 'ventas_diarias') or not self.ventas_diarias:
            return "Análisis: Cargando datos..."
            
        import datetime
        hoy = datetime.date.today()
        dia_actual = hoy.day
        
        # Filtrar meses válidos (excluyendo abril - mes 04 por ser periodo de prueba)
        meses_historicos = [m for m in sorted(self.datos_cache.keys(), reverse=True) if not m.endswith("-04")]
        
        if len(meses_historicos) < 3: return "Análisis: Se requieren al menos 3 meses de histórico (excluyendo periodos de prueba)."

        def obtener_venta_hasta_dia(prefijo_mes, limite_dia):
            total = Decimal(0)
            for fecha, monto in self.ventas_diarias.items():
                if fecha.startswith(prefijo_mes):
                    try:
                        dia_fecha = int(fecha[8:10])
                        if dia_fecha <= limite_dia:
                            total += monto
                    except: continue
            return total

        # m1: Mes actual hasta hoy (SUMA DE TODAS LAS SUCURSALES)
        m1 = obtener_venta_hasta_dia(meses_historicos[0], dia_actual)
        # m2 y m3: Meses anteriores comparados HASTA EL MISMO DÍA (SUMA DE TODAS LAS SUCURSALES)
        m2 = obtener_venta_hasta_dia(meses_historicos[1], dia_actual)
        m3 = obtener_venta_hasta_dia(meses_historicos[2], dia_actual)
        
        if m2 == 0 or m3 == 0: return "Análisis: Comparativa diaria en proceso..."

        # Cálculo de aceleración y tendencia
        crec1 = m1 - m2
        crec2 = m2 - m3
        aceleracion = crec1 - crec2
        
        # Proyección fin de mes (Lineal según promedio diario actual de TODO el negocio)
        venta_total_mes_actual = sum(self.datos_cache[meses_historicos[0]].values())
        proyeccion_mes = (venta_total_mes_actual / Decimal(dia_actual)) * Decimal(30)
        
        estado = "CRECIMIENTO CONSOLIDADO DETECTADO" if m1 > m2 else "RITMO GLOBAL INFERIOR AL MES PASADO"
        
        return (
            f"--- ESTUDIO DE COMPARATIVA DIARIA CONSOLIDADA (Día {dia_actual}) ---\n"
            f"1. Estado actual: {estado}\n"
            f"2. Ventas totales hoy vs mismo día mes pasado: {'+' if m1 > m2 else ''}{_formato_moneda(m1-m2)}\n"
            f"3. Aceleración del negocio: {'Ganando fuerza' if aceleracion > 0 else 'Ritmo estable/lento'}\n"
            f"4. Proyección fin de mes (Todo el negocio): {_formato_moneda(proyeccion_mes)}\n\n"
            f"EXPLICACIÓN: Este análisis suma las ventas de COQUIMBO y LA SERENA para darte\n"
            f"una visión global de tu empresa. Compara lo que llevas vendido hoy ({hoy.strftime('%d %b')})\n"
            f"contra el total de ambos locales en la misma fecha los meses anteriores.\n"
            f"(Nota: Mes de prueba 04 excluido)"
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