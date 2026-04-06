import tkinter as tk
from tkinter import ttk, messagebox
import requests
import time
import threading
import os
import queue
import datetime
import json
import sys
import subprocess
try:
    from escpos.printer import Network
except Exception:
    Network = None

# CONFIGURACIÓN ESPECÍFICA PARA LA SERENA
SUCURSAL = "La Serena"
API_URL = os.environ.get("API_URL", "https://sitiolaserena.onrender.com/api")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")
PRINTER_IP = os.environ.get("PRINTER_IP", "192.168.1.108")
TOP_BAR_BG = "#333"
APP_VERSION = "2026.04.06.2"
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/joselopezr1234567/sitiolaserena/main/app_version.json"

def _parse_version(v: str):
    parts = []
    for p in str(v or "").replace("-", ".").split("."):
        if p.isdigit():
            parts.append(int(p))
        else:
            n = ""
            for ch in p:
                if ch.isdigit():
                    n += ch
                else:
                    break
            if n:
                parts.append(int(n))
    return tuple(parts)

def _is_newer(remote: str, local: str):
    return _parse_version(remote) > _parse_version(local)

def _write_text(path: str, content: str):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

def _run_update_helper(python_exe: str, target_path: str, new_path: str, argv_tail):
    helper_path = os.path.join(os.path.dirname(target_path), f"._update_helper_{int(time.time())}.py")
    helper_code = r'''
import os, sys, time, subprocess
python_exe = sys.argv[1]
target_path = sys.argv[2]
new_path = sys.argv[3]
argv_tail = sys.argv[4:]
ok = False
for _ in range(120):
    try:
        os.replace(new_path, target_path)
        ok = True
        break
    except Exception:
        time.sleep(0.5)
if ok:
    subprocess.Popen([python_exe, target_path, *argv_tail], close_fds=False)
'''
    _write_text(helper_path, helper_code.strip() + "\n")
    try:
        subprocess.Popen([python_exe, helper_path, python_exe, target_path, new_path, *argv_tail], close_fds=False)
    except Exception:
        pass

def _admin_headers():
    if not ADMIN_API_TOKEN:
        return {}
    return {"x-admin-token": ADMIN_API_TOKEN}

class DashboardPizzeria:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Dashboard de Pedidos - {SUCURSAL}")
        self.root.geometry("1000x600")
        self.root.configure(bg="#111")

        self.pedidos_vistos = set()
        self.pedidos_impresos = set()
        self.running = True
        self.print_status_var = tk.StringVar(value="Impresión: -")
        self.print_status_color = "#ffffff"
        self._auth_warned = False
        if not ADMIN_API_TOKEN:
            self._auth_warned = True
            messagebox.showwarning("Token faltante", "Falta ADMIN_API_TOKEN. Este dashboard no podrá ver pedidos hasta configurarlo.")
        self._start_auto_update_check()
        
        # Cola de impresión
        self.print_queue = queue.Queue()
        threading.Thread(target=self.process_print_queue, daemon=True).start()
        
        # Estilos
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#222", foreground="white", fieldbackground="#222", rowheight=30)
        style.map("Treeview", background=[('selected', '#FF0000')])

        header = tk.Frame(root, bg=TOP_BAR_BG)
        header.pack(fill=tk.X)
        title_label = tk.Label(header, text=f"PEDIDOS ENTRANTES - {SUCURSAL.upper()}", font=("Arial", 24, "bold"), fg="#ffffff", bg=TOP_BAR_BG)
        title_label.pack(pady=15)
        self.print_status_label = tk.Label(header, textvariable=self.print_status_var, font=("Arial", 12, "bold"), fg=self.print_status_color, bg=TOP_BAR_BG)
        self.print_status_label.pack(side=tk.RIGHT, padx=20)

        # Tabla de Pedidos
        columns = ("id", "usuario", "telefono", "productos", "total", "estado", "fecha")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        
        self.tree.heading("id", text="ID")
        self.tree.heading("usuario", text="Cliente")
        self.tree.heading("telefono", text="Teléfono")
        self.tree.heading("productos", text="Productos")
        self.tree.heading("total", text="Total")
        self.tree.heading("estado", text="Estado")
        self.tree.heading("fecha", text="Fecha")

        self.tree.column("id", width=50)
        self.tree.column("usuario", width=120)
        self.tree.column("telefono", width=100)
        self.tree.column("productos", width=250)
        self.tree.column("total", width=80)
        self.tree.column("estado", width=100)
        self.tree.column("fecha", width=140)

        self.tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        # Panel de Configuración de Demora
        config_frame = tk.Frame(root, bg="#222", bd=2, relief=tk.RAISED)
        config_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(config_frame, text="TIEMPO DE DEMORA (MINUTOS):", font=("Arial", 12, "bold"), fg="#ffffff", bg="#222").pack(side=tk.LEFT, padx=10, pady=10)
        
        self.demora_var = tk.StringVar(value="30")
        self.entry_demora = tk.Entry(config_frame, textvariable=self.demora_var, font=("Arial", 12), width=5, justify='center')
        self.entry_demora.pack(side=tk.LEFT, padx=5)
        
        self.btn_guardar_demora = tk.Button(config_frame, text="ACTUALIZAR TIEMPO", command=self.actualizar_demora, 
                                            bg="#FF0000", fg="black", font=("Arial", 10, "bold"))
        self.btn_guardar_demora.pack(side=tk.LEFT, padx=10)

        self.estado_local_var = tk.StringVar(value="Estado: -")
        tk.Label(config_frame, textvariable=self.estado_local_var, font=("Arial", 12, "bold"), fg="#FFD700", bg="#222").pack(side=tk.LEFT, padx=10)
        self.btn_estado_local = tk.Button(config_frame, text="CAMBIAR ESTADO", command=self.toggle_estado_local, bg="#DDDDDD", fg="black", font=("Arial", 10, "bold"))
        self.btn_estado_local.pack(side=tk.LEFT, padx=10)

        # Botones de Acción y Herramientas (Abajo)
        btn_frame = tk.Frame(root, bg="#111")
        btn_frame.pack(fill=tk.X, pady=20, padx=20)

        # Contenedor para botones de la izquierda (Cierre)
        left_btns = tk.Frame(btn_frame, bg="#111")
        left_btns.pack(side=tk.LEFT)
        
        self.btn_cierre = tk.Button(left_btns, text="CIERRE DE CAJA", command=self.abrir_cierre_caja,
                                   fg="black", activeforeground="black",
                                   bg="#DDDDDD", activebackground="#CCCCCC",
                                   highlightthickness=0, bd=0,
                                   font=("Arial", 12, "bold"), width=20)
        self.btn_cierre.pack(side=tk.LEFT)

        # Contenedor para botones centrales (Pedido Listo)
        center_btns = tk.Frame(btn_frame, bg="#111")
        center_btns.pack(side=tk.LEFT, expand=True)

        self.btn_listo = tk.Button(center_btns, text="PEDIDO LISTO", command=self.pedido_listo, 
                                   bg="#ffffff", fg="black", font=("Arial", 12, "bold"), width=30)
        self.btn_listo.pack()

        # Contenedor para botones de la derecha (Productos)
        right_btns = tk.Frame(btn_frame, bg="#111")
        right_btns.pack(side=tk.RIGHT)
        
        self.btn_productos = tk.Button(right_btns, text="PRODUCTOS", command=self.gestionar_productos,
                                   fg="black", activeforeground="black",
                                   bg="#DDDDDD", activebackground="#CCCCCC",
                                   highlightthickness=0, bd=0,
                                   font=("Arial", 12, "bold"), width=15)
        self.btn_productos.pack(side=tk.RIGHT)

        # Hilo para actualizar pedidos
        self.update_thread = threading.Thread(target=self.poll_orders, daemon=True)
        self.update_thread.start()
        
        # Cargar demora inicial
        self.cargar_demora_inicial()
        self.cargar_estado_local()

    def _start_auto_update_check(self):
        def worker():
            try:
                url = UPDATE_MANIFEST_URL + "?t=" + str(int(time.time()))
                r = requests.get(url, timeout=8)
                if r.status_code != 200:
                    return
                data = r.json()
                remote_version = str(data.get("version") or "")
                if not remote_version:
                    return
                if not _is_newer(remote_version, APP_VERSION):
                    return
                app_key = os.path.basename(__file__)
                app_info = (data.get("apps") or {}).get(app_key) or {}
                file_url = str(app_info.get("url") or "")
                if not file_url:
                    return
                self.root.after(0, lambda: self._show_update_window(remote_version, file_url))
            except Exception:
                return

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_window(self, remote_version: str, file_url: str):
        win = tk.Toplevel(self.root)
        win.title("Actualizar versión")
        win.configure(bg="#111")
        win.geometry("520x240")
        win.grab_set()

        tk.Label(win, text="Hay una nueva versión disponible", fg="#ffffff", bg="#111", font=("Arial", 16, "bold")).pack(pady=(20, 10))
        tk.Label(win, text=f"Versión instalada: {APP_VERSION}", fg="#bbbbbb", bg="#111", font=("Arial", 12)).pack()
        tk.Label(win, text=f"Nueva versión: {remote_version}", fg="#FFD700", bg="#111", font=("Arial", 12, "bold")).pack(pady=(0, 10))

        status = tk.StringVar(value="")
        tk.Label(win, textvariable=status, fg="#ffffff", bg="#111", font=("Arial", 11)).pack(pady=(10, 0))

        btns = tk.Frame(win, bg="#111")
        btns.pack(pady=20)

        def do_update():
            def run():
                try:
                    status.set("Descargando actualización...")
                    r = requests.get(file_url + "?t=" + str(int(time.time())), timeout=15)
                    if r.status_code != 200 or not r.text.strip():
                        status.set("No se pudo descargar la actualización")
                        return
                    target_path = os.path.abspath(__file__)
                    new_path = target_path + ".new"
                    _write_text(new_path, r.text)
                    status.set("Aplicando actualización...")
                    self.root.after(0, lambda: win.destroy())
                    _run_update_helper(sys.executable, target_path, new_path, sys.argv[1:])
                    try:
                        self.root.destroy()
                    except Exception:
                        pass
                    os._exit(0)
                except Exception:
                    status.set("Error al actualizar")
            threading.Thread(target=run, daemon=True).start()

        tk.Button(btns, text="ACTUALIZAR AHORA", command=do_update, bg="#00FF00", fg="black", font=("Arial", 12, "bold"), width=18).pack(side=tk.LEFT, padx=10)
        tk.Button(btns, text="MÁS TARDE", command=win.destroy, bg="#555", fg="black", font=("Arial", 12, "bold"), width=12).pack(side=tk.LEFT, padx=10)

    def cargar_demora_inicial(self):
        try:
            response = requests.get(f"{API_URL}/config/{SUCURSAL}")
            if response.status_code == 200:
                data = response.json()
                self.demora_var.set(str(data['demora_actual']))
        except Exception as e:
            print(f"Error al cargar demora: {e}")

    def cargar_estado_local(self):
        try:
            response = requests.get(f"{API_URL}/config/{SUCURSAL}", headers=_admin_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.estado_local_var.set("Estado: CERRADO" if (data.get("cerrado") is True) else "Estado: ABIERTO")
            else:
                self.estado_local_var.set("Estado: ERROR")
        except Exception:
            self.estado_local_var.set("Estado: ERROR")
        self.root.after(30000, self.cargar_estado_local)

    def toggle_estado_local(self):
        try:
            getr = requests.get(f"{API_URL}/config/{SUCURSAL}", headers=_admin_headers(), timeout=10)
            cur_cerrado = False
            if getr.status_code == 200:
                cur_cerrado = bool(getr.json().get("cerrado"))
            upr = requests.put(f"{API_URL}/config/{SUCURSAL}", json={"cerrado": (not cur_cerrado)}, headers=_admin_headers(), timeout=10)
            if upr.status_code == 200:
                self.cargar_estado_local()
            elif upr.status_code == 401:
                messagebox.showerror("No autorizado", "Token inválido o faltante. Revisa ADMIN_API_TOKEN en este PC.")
            else:
                messagebox.showerror("Error", "No se pudo cambiar el estado del local")
        except Exception:
            messagebox.showerror("Error", "No hay conexión con el servidor")

    def actualizar_demora(self):
        try:
            nueva_demora = int(self.demora_var.get())
            response = requests.put(f"{API_URL}/config/{SUCURSAL}", json={"demora_actual": nueva_demora}, headers=_admin_headers(), timeout=10)
            if response.status_code == 200:
                messagebox.showinfo("Éxito", f"Tiempo de demora actualizado a {nueva_demora} minutos.")
            else:
                messagebox.showerror("Error", "No se pudo actualizar el tiempo.")
        except ValueError:
            messagebox.showwarning("Atención", "Por favor ingresa un número válido.")
        except Exception as e:
            messagebox.showerror("Error", f"Error de conexión: {e}")

    def poll_orders(self):
        while self.running:
            try:
                # Se envía el filtro de sucursal en la URL
                response = requests.get(f"{API_URL}/admin/pedidos?sucursal={SUCURSAL}", headers=_admin_headers())
                if response.status_code == 200:
                    pedidos = response.json()
                    
                    # Inicializar los pedidos vistos la primera vez
                    if not self.pedidos_vistos:
                        for p in pedidos:
                            self.pedidos_vistos.add(p['id'])
                            if p.get('estado') in ['pagado', 'preparando', 'listo']:
                                self.pedidos_impresos.add(p['id'])
                    
                    self.root.after(0, self.update_table, pedidos)
                elif response.status_code == 401 and not self._auth_warned:
                    self._auth_warned = True
                    self.root.after(0, lambda: messagebox.showerror("No autorizado", "Token inválido o faltante. Revisa ADMIN_API_TOKEN en este PC."))
            except Exception as e:
                print(f"Error al obtener pedidos: {e}")
            time.sleep(5)

    def update_table(self, pedidos):
        # Guardar selección actual
        selected_item = self.tree.selection()
        selected_id = None
        if selected_item:
            selected_id = self.tree.item(selected_item)['values'][0]

        # Limpiar tabla
        for item in self.tree.get_children():
            self.tree.delete(item)

        for p in pedidos:
            # Crear un string resumen de los productos con más detalle
            detalles_prods = []
            for prod in p.get('productos', []):
                nombre = prod['producto_nombre']
                extra = prod.get('detalles', '')
                if extra:
                    # Extraer solo el nombre de la pizza si viene en el formato "NOMBRE ($PRECIO) | Ingredientes..."
                    if " | " in extra:
                        pizza_nombre = extra.split(" | ")[0].split(" ($")[0]
                        detalles_prods.append(f"{nombre}: {pizza_nombre}")
                    else:
                        detalles_prods.append(f"{nombre}: {extra}")
                else:
                    detalles_prods.append(nombre)
            
            resumen_prods = " + ".join(detalles_prods)
            
            self.tree.insert("", tk.END, values=(
                p['id'], p['usuario_nombre'], p['telefono'], resumen_prods, 
                f"${p['total']}", p['estado'], str(p.get('fecha', ''))[:16]
            ))
            
            if p.get('estado') in ['pagado', 'preparando'] and p['id'] not in self.pedidos_impresos:
                self.print_queue.put(p)
                self.pedidos_impresos.add(p['id'])
            self.pedidos_vistos.add(p['id'])

        # Restaurar selección
        if selected_id:
            for item in self.tree.get_children():
                if self.tree.item(item)['values'][0] == selected_id:
                    self.tree.selection_set(item)
                    break

    def process_print_queue(self):
        while self.running:
            try:
                pedido = self.print_queue.get(timeout=1)
                self.imprimir_ticket(pedido)
                self.print_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error en el hilo de impresión: {e}")

    def _set_print_status(self, texto: str, color: str):
        self.print_status_var.set(texto)
        self.print_status_label.configure(fg=color)

    def imprimir_ticket(self, pedido):
        try:
            pedido_id = pedido.get('id')
            cliente = pedido.get('usuario_nombre', '')
            productos = pedido.get('productos', [])
            total = pedido.get('total')

            if Network:
                p = Network(PRINTER_IP)
                p.set(align="center", width=2, height=2, bold=True)
                p.text("PEDIDO WEB\n")
                p.set(align="left", width=1, height=1, bold=False)
                p.text(f"Pedido #{pedido_id}\n")
                p.text(f"Cliente: {cliente}\n")
                p.text("\nProductos:\n")
                for prod in productos:
                    nombre = prod.get('producto_nombre', '')
                    det = prod.get('detalles') or ""
                    p.text(f"- {nombre}\n")
                    if det:
                        p.text(f"  {det}\n")
                p.text("\n")
                p.set(align="left", width=1, height=1, bold=True)
                p.text(f"TOTAL: ${total}\n")
                p.set(align="left", width=1, height=1, bold=False)
                p.text("\n")
                p.cut()
                p.close()
                self.root.after(0, lambda: self._set_print_status(f"Impresión OK: Pedido #{pedido_id}", "#00FF00"))
            else:
                lineas = []
                lineas.append("PEDIDO WEB")
                lineas.append(f"Pedido #{pedido_id}")
                lineas.append(f"Cliente: {cliente}")
                lineas.append("")
                lineas.append("Productos:")
                for prod in productos:
                    nombre = prod.get('producto_nombre', '')
                    det = prod.get('detalles') or ""
                    lineas.append(f"- {nombre}")
                    if det:
                        lineas.append(f"  {det}")
                lineas.append("")
                lineas.append(f"TOTAL: ${total}")
                lineas.append("")
                print("\n".join(lineas))
                self.root.after(0, lambda: self._set_print_status("Error impresión: falta python-escpos", "#FF0000"))
            
        except Exception as e:
            print(f"Error al imprimir en {PRINTER_IP}: {e}")
            self.root.after(0, lambda: self._set_print_status(f"Error impresión: Pedido #{pedido.get('id')}", "#FF0000"))

    def pedido_listo(self):
        selected = self.tree.selection()
        if not selected:
            return
        
        pedido_id = self.tree.item(selected)['values'][0]
        self.update_status(pedido_id, "listo")

    def update_status(self, pedido_id, nuevo_estado):
        try:
            response = requests.put(f"{API_URL}/pedidos/{pedido_id}/estado", json={"estado": nuevo_estado})
            if response.status_code != 200:
                print(f"Error al actualizar pedido {pedido_id}")
        except Exception as e:
            print(f"Error de conexión: {e}")

    def gestionar_productos(self):
        # Crear ventana hija para gestionar productos
        prod_win = tk.Toplevel(self.root)
        prod_win.title(f"Gestión de Productos - {SUCURSAL}")
        prod_win.geometry("600x500")
        prod_win.configure(bg="#111")
        
        tk.Label(prod_win, text="ESTADO DE PRODUCTOS", font=("Arial", 16, "bold"), bg="#111", fg="#ffffff").pack(pady=15)
        
        # Frame para la lista con scroll
        list_frame = tk.Frame(prod_win, bg="#111")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        canvas = tk.Canvas(list_frame, bg="#111", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#111")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Variables para guardar el estado de los checkboxes
        self.prod_vars = {}
        
        def cargar_productos_desde_api():
            # Limpiar el frame
            for widget in scrollable_frame.winfo_children():
                widget.destroy()
                
            try:
                # Consultar productos de la sucursal (usando formato la_serena que está en la base de datos)
                sucursal_db = "la_serena" if SUCURSAL == "La Serena" else SUCURSAL.lower()
                response = requests.get(f"{API_URL}/productos?sucursal={sucursal_db}")
                if response.status_code == 200:
                    productos = response.json()
                    
                    for p in productos:
                        prod_id = p['id']
                        nombre = p['nombre']
                        # Si disponible es true o false
                        disponible = p.get('disponible', True)
                        
                        var = tk.BooleanVar(value=disponible)
                        self.prod_vars[prod_id] = var
                        
                        item_frame = tk.Frame(scrollable_frame, bg="#222", bd=1, relief=tk.SOLID)
                        item_frame.pack(fill=tk.X, pady=5, padx=5)
                        
                        tk.Label(item_frame, text=nombre, font=("Arial", 12), bg="#222", fg="white", width=30, anchor="w").pack(side=tk.LEFT, padx=10, pady=10)
                        
                        # Checkbox: Agotado / Disponible
                        chk = tk.Checkbutton(item_frame, text="Disponible", variable=var, 
                                           command=lambda pid=prod_id, v=var: actualizar_estado_prod(pid, v.get()),
                                           bg="#222", fg="#00FF00" if disponible else "#FF0000", selectcolor="#111", font=("Arial", 10, "bold"))
                        chk.pack(side=tk.RIGHT, padx=10)
                        
                        # Cambiar color del texto según estado
                        def update_color(chk_widget, is_avail):
                            chk_widget.config(fg="#00FF00" if is_avail else "#FF0000", text="Disponible" if is_avail else "Agotado")
                            
                        update_color(chk, disponible)
                        
                else:
                    tk.Label(scrollable_frame, text="Error al cargar productos", fg="red", bg="#111").pack()
            except Exception as e:
                tk.Label(scrollable_frame, text=f"Error de conexión: {e}", fg="red", bg="#111").pack()

        def actualizar_estado_prod(prod_id, is_disponible):
            try:
                response = requests.put(f"{API_URL}/admin/productos/{prod_id}/disponibilidad", json={"disponible": is_disponible}, headers=_admin_headers())
                if response.status_code == 200:
                    # Recargar para actualizar colores
                    cargar_productos_desde_api()
                else:
                    messagebox.showerror("Error", "No se pudo actualizar el producto")
                    cargar_productos_desde_api() # Revertir visualmente
            except Exception as e:
                messagebox.showerror("Error", f"Fallo de conexión: {e}")
                cargar_productos_desde_api()
                
        # Cargar la primera vez
        cargar_productos_desde_api()

    def abrir_cierre_caja(self):
        win = tk.Toplevel(self.root)
        win.title(f"Cierre de Caja - {SUCURSAL}")
        win.geometry("900x550")
        win.configure(bg="#111")

        header = tk.Frame(win, bg=TOP_BAR_BG)
        header.pack(fill=tk.X, padx=15, pady=15)

        fecha_var = tk.StringVar(value=datetime.date.today().strftime("%Y-%m-%d"))
        lbl_titulo = tk.Label(header, text=f"CIERRE DE CAJA - {SUCURSAL.upper()}", font=("Arial", 16, "bold"), fg="#ffffff", bg=TOP_BAR_BG)
        lbl_titulo.pack(side=tk.LEFT, padx=10, pady=10)

        total_var = tk.StringVar(value="TOTAL: $0")
        lbl_total = tk.Label(header, textvariable=total_var, font=("Arial", 16, "bold"), fg="#00FF00", bg=TOP_BAR_BG)
        lbl_total.pack(side=tk.RIGHT, padx=10, pady=10)

        filtros = tk.Frame(win, bg="#111")
        filtros.pack(fill=tk.X, padx=15, pady=(0, 10))

        tk.Label(filtros, text="FECHA (YYYY-MM-DD):", font=("Arial", 12, "bold"), fg="#ffffff", bg="#111").pack(side=tk.LEFT)
        tk.Entry(filtros, textvariable=fecha_var, font=("Arial", 12), width=12, justify="center").pack(side=tk.LEFT, padx=10)

        def cambiar_dia(delta: int):
            try:
                actual = datetime.date.fromisoformat(fecha_var.get().strip())
            except Exception:
                actual = datetime.date.today()
            nueva = actual + datetime.timedelta(days=delta)
            fecha_var.set(nueva.strftime("%Y-%m-%d"))
            threading.Thread(target=cargar, daemon=True).start()

        tk.Button(filtros, text="◀", command=lambda: cambiar_dia(-1), bg="#555", fg="black", font=("Arial", 11, "bold"), width=3).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(filtros, text="HOY", command=lambda: (fecha_var.set(datetime.date.today().strftime("%Y-%m-%d")), threading.Thread(target=cargar, daemon=True).start()), bg="#DDDDDD", fg="black", font=("Arial", 11, "bold"), width=6).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(filtros, text="▶", command=lambda: cambiar_dia(1), bg="#555", fg="black", font=("Arial", 11, "bold"), width=3).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(filtros, text="CARGAR", command=lambda: threading.Thread(target=cargar, daemon=True).start(), bg="#00FF00", fg="black", font=("Arial", 11, "bold"), width=10).pack(side=tk.LEFT)

        columns = ("id", "hora", "cliente", "telefono", "total")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        tree.heading("id", text="ID")
        tree.heading("hora", text="Hora")
        tree.heading("cliente", text="Cliente")
        tree.heading("telefono", text="Teléfono")
        tree.heading("total", text="Total")

        tree.column("id", width=60)
        tree.column("hora", width=100)
        tree.column("cliente", width=220)
        tree.column("telefono", width=140)
        tree.column("total", width=120)

        tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        def cargar():
            try:
                fecha_filtro = fecha_var.get().strip()
                response = requests.get(f"{API_URL}/admin/cierre", params={"sucursal": SUCURSAL, "fecha": fecha_filtro}, headers=_admin_headers())
                if response.status_code != 200:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No se pudo obtener el cierre de caja"))
                    return
                data = response.json()
                pedidos = data.get("pedidos", [])
                total_dia = data.get("total_dia", 0)

                def pintar():
                    lbl_titulo.configure(text=f"CIERRE DE CAJA - {SUCURSAL.upper()} ({fecha_filtro})")
                    for item in tree.get_children():
                        tree.delete(item)
                    for p in pedidos:
                        fecha_local = str(p.get("fecha", ""))[:19]
                        hora = fecha_local[11:16] if len(fecha_local) >= 16 else fecha_local
                        
                        estado_str = f" ({p.get('estado', 'pagado').upper()})" if p.get('estado') == 'listo' else ""
                        cliente_nombre = p.get("usuario_nombre", "") + estado_str
                        
                        tree.insert("", tk.END, values=(
                            p.get("id", ""),
                            hora,
                            cliente_nombre,
                            p.get("telefono", ""),
                            f"${int(p.get('total', 0)):,}".replace(",", ".")
                        ))
                    total_var.set(f"TOTAL: ${int(total_dia):,}".replace(",", "."))

                self.root.after(0, pintar)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error de conexión: {e}"))

        threading.Thread(target=cargar, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = DashboardPizzeria(root)
    root.mainloop()
