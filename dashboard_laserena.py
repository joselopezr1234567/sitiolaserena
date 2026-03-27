import tkinter as tk
from tkinter import ttk, messagebox
import requests
import time
import threading
import os
import queue
try:
    from escpos.printer import Network
except Exception:
    Network = None

# CONFIGURACIÓN ESPECÍFICA PARA LA SERENA
SUCURSAL = "La Serena"
API_URL = os.environ.get("API_URL", "https://sitiolaserena.onrender.com/api")
PRINTER_IP = "192.168.1.108" # POR FAVOR ACTUALIZA ESTA IP PARA LA SERENA

class DashboardPizzeria:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Dashboard de Pedidos - {SUCURSAL}")
        self.root.geometry("1000x600")
        self.root.configure(bg="#111")

        self.pedidos_vistos = set()
        self.running = True
        
        # Cola de impresión
        self.print_queue = queue.Queue()
        threading.Thread(target=self.process_print_queue, daemon=True).start()
        
        # Estilos
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#222", foreground="white", fieldbackground="#222", rowheight=30)
        style.map("Treeview", background=[('selected', '#FF0000')])

        # Título
        title_label = tk.Label(root, text=f"PEDIDOS ENTRANTES - {SUCURSAL.upper()}", font=("Arial", 24, "bold"), fg="#FF0000", bg="#111")
        title_label.pack(pady=20)

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

    def cargar_demora_inicial(self):
        try:
            response = requests.get(f"{API_URL}/config/{SUCURSAL}")
            if response.status_code == 200:
                data = response.json()
                self.demora_var.set(str(data['demora_actual']))
        except Exception as e:
            print(f"Error al cargar demora: {e}")

    def actualizar_demora(self):
        try:
            nueva_demora = int(self.demora_var.get())
            response = requests.put(f"{API_URL}/config/{SUCURSAL}", json={"demora_actual": nueva_demora})
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
                response = requests.get(f"{API_URL}/admin/pedidos?sucursal={SUCURSAL}")
                if response.status_code == 200:
                    pedidos = response.json()
                    
                    # Inicializar los pedidos vistos la primera vez
                    if not self.pedidos_vistos:
                        for p in pedidos:
                            self.pedidos_vistos.add(p['id'])
                    
                    self.root.after(0, self.update_table, pedidos)
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
            
            # Si el pedido es nuevo y está en estado 'preparando' (recién llegado)
            if p['id'] not in self.pedidos_vistos:
                if p['estado'] in ['pagado', 'preparando']:
                    # Encolar para impresión
                    self.print_queue.put(p)
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

    def imprimir_ticket(self, pedido):
        try:
            # En producción se usa la impresora real
            # p = Network(PRINTER_IP)
            
            # Formato del Ticket
            print(f"\n--- TICKET IMPRESIÓN ---")
            print(f"PEDIDO #{pedido['id']}")
            print(f"CLIENTE: {pedido['usuario_nombre']}")
            print("-" * 32)
            
            print("PRODUCTOS:")
            for prod in pedido.get('productos', []):
                print(f"- {prod['producto_nombre']}")
                if prod['detalles']:
                    print(f"  Detalle: {prod['detalles']}")
            
            print("-" * 32)
            print(f"TOTAL: ${pedido['total']}")
            print(f"------------------------\n")
            
        except Exception as e:
            print(f"Error al imprimir en {PRINTER_IP}: {e}")

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
                response = requests.put(f"{API_URL}/admin/productos/{prod_id}/disponibilidad", json={"disponible": is_disponible})
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

        header = tk.Frame(win, bg="#222")
        header.pack(fill=tk.X, padx=15, pady=15)

        lbl_titulo = tk.Label(header, text=f"CIERRE DE CAJA - {SUCURSAL.upper()} (HOY)", font=("Arial", 16, "bold"), fg="#ffffff", bg="#222")
        lbl_titulo.pack(side=tk.LEFT, padx=10, pady=10)

        total_var = tk.StringVar(value="TOTAL: $0")
        lbl_total = tk.Label(header, textvariable=total_var, font=("Arial", 16, "bold"), fg="#00FF00", bg="#222")
        lbl_total.pack(side=tk.RIGHT, padx=10, pady=10)

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
                response = requests.get(f"{API_URL}/admin/cierre", params={"sucursal": SUCURSAL})
                if response.status_code != 200:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No se pudo obtener el cierre de caja"))
                    return
                data = response.json()
                pedidos = data.get("pedidos", [])
                total_dia = data.get("total_dia", 0)

                def pintar():
                    for item in tree.get_children():
                        tree.delete(item)
                    for p in pedidos:
                        fecha = str(p.get("fecha", ""))[:19]
                        hora = fecha[11:16] if len(fecha) >= 16 else fecha
                        
                        estado_str = f" ({p.get('estado', 'pagado').upper()})" if p.get('estado') == 'listo' else ""
                        cliente_nombre = p.get("usuario_nombre", "") + estado_str
                        
                        tree.insert("", tk.END, values=(
                            p.get("id", ""),
                            hora,
                            cliente_nombre,
                            p.get("telefono", ""),
                            f"${int(p.get('total', 0))}"
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
