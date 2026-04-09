import tkinter as tk
from tkinter import ttk, messagebox
import requests
import os
import json
import threading
import sys
import subprocess
import time

API_URL = os.environ.get("API_URL", "https://sitiolaserena.onrender.com/api")
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")
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

class AdminManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Administración de Pizzería - Fácil")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(900, max(720, sw - 80))
        h = min(800, max(600, sh - 120))
        self.root.geometry(f"{w}x{h}")
        self.root.configure(bg="#1a1a1a")
        
        self.usuario_actual = None
        self.admin_token = None
        self.sucursal_activa = None
        self.productos_lista = []
        self.todos_productos = []
        self.after_id = None
        self.modo_nuevo = False
        self._skip_update_version = None
        self._start_auto_update_check()
        self.mostrar_login()

    def limpiar_pantalla(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        for widget in self.root.winfo_children():
            widget.destroy()

    def _scroll_container(self, parent):
        wrapper = tk.Frame(parent, bg="#1a1a1a")
        canvas = tk.Canvas(wrapper, bg="#1a1a1a", highlightthickness=0)
        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg="#1a1a1a")
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(_evt=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(evt):
            canvas.itemconfigure(window_id, width=evt.width)

        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def _bind_mousewheel(_evt=None):
            def _on_mousewheel(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            def _on_linux_up(_e):
                canvas.yview_scroll(-1, "units")
            def _on_linux_down(_e):
                canvas.yview_scroll(1, "units")
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_linux_up)
            canvas.bind_all("<Button-5>", _on_linux_down)

        def _unbind_mousewheel(_evt=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        return wrapper, inner

    def mostrar_login(self):
        self.limpiar_pantalla()
        login_frame = tk.Frame(self.root, bg="#1a1a1a")
        login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        tk.Label(login_frame, text="ENTRADA AL SISTEMA", font=("Arial", 24, "bold"), fg="#FF0000", bg="#1a1a1a").pack(pady=30)
        
        tk.Label(login_frame, text="Usuario (opcional):", fg="white", bg="#1a1a1a", font=("Arial", 14)).pack()
        self.ent_user = tk.Entry(login_frame, font=("Arial", 16), width=20, justify='center')
        self.ent_user.pack(pady=10)
        self.ent_user.insert(0, "admin")

        tk.Label(login_frame, text="Token de acceso:", fg="white", bg="#1a1a1a", font=("Arial", 14)).pack()
        self.ent_pass = tk.Entry(login_frame, font=("Arial", 16), show="*", width=20, justify='center')
        self.ent_pass.pack(pady=10)

        tk.Button(login_frame, text="INGRESAR AHORA", command=self.login, bg="#00FF00", fg="black", font=("Arial", 14, "bold"), width=20, height=2, cursor="hand2").pack(pady=30)

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
        win.configure(bg="#1a1a1a")
        win.geometry("520x240")
        win.grab_set()

        tk.Label(win, text="Hay una nueva versión disponible", fg="#ffffff", bg="#1a1a1a", font=("Arial", 16, "bold")).pack(pady=(20, 10))
        tk.Label(win, text=f"Versión instalada: {APP_VERSION}", fg="#bbbbbb", bg="#1a1a1a", font=("Arial", 12)).pack()
        tk.Label(win, text=f"Nueva versión: {remote_version}", fg="#FFD700", bg="#1a1a1a", font=("Arial", 12, "bold")).pack(pady=(0, 10))

        status = tk.StringVar(value="")
        tk.Label(win, textvariable=status, fg="#ffffff", bg="#1a1a1a", font=("Arial", 11)).pack(pady=(10, 0))

        btns = tk.Frame(win, bg="#1a1a1a")
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

    def _headers(self):
        if not self.admin_token:
            return {}
        return {"x-admin-token": self.admin_token}

    def login(self):
        user = (self.ent_user.get() or "admin").strip()
        token = (self.ent_pass.get() or "").strip() or (ADMIN_API_TOKEN or "").strip()
        try:
            if not token:
                messagebox.showerror("Error", "Falta token. Configura ADMIN_API_TOKEN o pégalo aquí.")
                return
            self.admin_token = token
            res = requests.get(f"{API_URL}/admin/ping", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                self.usuario_actual = {"nombre": user, "telefono": "", "rol": "admin"}
                self.mostrar_menu_principal()
                return
            messagebox.showerror("Error", "Token inválido")
        except:
            messagebox.showerror("Error", "No hay conexión con el servidor")

    def mostrar_menu_principal(self):
        self.limpiar_pantalla()
        
        # Header simple
        header = tk.Frame(self.root, bg="#333", height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="PANEL PRINCIPAL", fg="white", bg="#333", font=("Arial", 18, "bold")).pack(pady=15)

        menu_frame = tk.Frame(self.root, bg="#1a1a1a")
        menu_frame.pack(expand=True)

        tk.Label(menu_frame, text="¿Qué local quieres ver?", font=("Arial", 20, "bold"), fg="#ffffff", bg="#1a1a1a").pack(pady=30)

        btn_style = {"font": ("Arial", 16, "bold"), "width": 30, "height": 3, "cursor": "hand2", "fg": "black"}

        tk.Button(menu_frame, text="🍕 PIZZERÍA LA SERENA", command=lambda: self.abrir_gestion_sucursal("la_serena"), bg="#FF0000", **btn_style).pack(pady=15)
        tk.Button(menu_frame, text="🍕 PIZZERÍA COQUIMBO", command=lambda: self.abrir_gestion_sucursal("coquimbo"), bg="#FF0000", **btn_style).pack(pady=15)
        tk.Button(menu_frame, text="👥 GESTIONAR USUARIOS", command=self.abrir_gestion_usuarios, bg="#555", **btn_style).pack(pady=15)
        tk.Button(menu_frame, text="⏱️ CIERRE DE LOCALES", command=self.abrir_cierre_locales, bg="#333", **btn_style).pack(pady=15)
        
        tk.Button(self.root, text="CERRAR SISTEMA", command=self.mostrar_login, bg="#333", fg="black", font=("Arial", 10, "bold")).pack(side=tk.BOTTOM, pady=20)

    def abrir_gestion_sucursal(self, sucursal):
        self.sucursal_activa = sucursal
        self.limpiar_pantalla()
        
        # Título arriba
        header = tk.Frame(self.root, bg="#333", height=70)
        header.pack(fill=tk.X)
        tk.Button(header, text="ATRÁS", command=self.mostrar_menu_principal, bg="black", fg="black", font=("Arial", 12, "bold"), width=10).pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(header, text=f"GESTIÓN: {sucursal.replace('_', ' ').upper()}", fg="white", bg="#333", font=("Arial", 20, "bold")).pack(side=tk.LEFT, padx=100)

        scroll_wrap, scroll_inner = self._scroll_container(self.root)
        scroll_wrap.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        content = tk.Frame(scroll_inner, bg="#1a1a1a")
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)

        # 1. Paso: Elegir Categoría
        tk.Label(content, text="PASO 1: Elige qué quieres gestionar", font=("Arial", 14, "bold"), fg="#ffffff", bg="#1a1a1a").pack(pady=10)
        
        cat_frame = tk.Frame(content, bg="#1a1a1a")
        cat_frame.pack(fill=tk.X)

        self.cb_filtro_cat = ttk.Combobox(cat_frame, font=("Arial", 16), state="readonly", width=20)
        self.cb_filtro_cat['values'] = ["PIZZAS", "MITADES", "BEBIDAS", "INGREDIENTES", "PROMOCIONES", "BASE", "ACOMPAÑAMIENTOS"]
        self.cb_filtro_cat.set("PIZZAS")
        self.cb_filtro_cat.pack(side=tk.LEFT, padx=10)
        self.cb_filtro_cat.bind("<<ComboboxSelected>>", lambda e: self.refrescar_lista_combo())

        # 2. Paso: Elegir Producto de esa categoría
        tk.Label(content, text="PASO 2: Elige el producto o pulsa 'NUEVO'", font=("Arial", 14, "bold"), fg="#ffffff", bg="#1a1a1a").pack(pady=10)
        
        sel_frame = tk.Frame(content, bg="#1a1a1a")
        sel_frame.pack(fill=tk.X)

        self.combo_productos = ttk.Combobox(sel_frame, font=("Arial", 16), state="readonly", width=40)
        self.combo_productos.pack(side=tk.LEFT, padx=10)
        self.combo_productos.bind("<<ComboboxSelected>>", self.seleccionar_producto_combo)

        self.btn_nuevo = tk.Button(sel_frame, text="➕ NUEVO", command=self.preparar_nuevo_producto, bg="#00FF00", fg="black", font=("Arial", 12, "bold"), width=10)
        self.btn_nuevo.pack(side=tk.LEFT, padx=10)

        # 3. Paso: Formulario (se activa al elegir algo)
        self.form_frame = tk.Frame(content, bg="#222", bd=2, relief=tk.GROOVE, padx=30, pady=20)
        self.form_frame.pack(fill=tk.BOTH, expand=True, pady=30)
        
        # Variables del formulario
        self.var_id = tk.StringVar()
        self.var_nombre = tk.StringVar()
        self.var_precio = tk.StringVar()
        self.var_cat = tk.StringVar()
        self.var_disp = tk.BooleanVar(value=True)

        # Campos visuales
        self.label_style = {"bg": "#222", "fg": "white", "font": ("Arial", 12, "bold")}
        self.entry_style = {"font": ("Arial", 14), "width": 35}

        self.lbl_nombre = tk.Label(self.form_frame, text="Nombre de la Pizza / Producto:", **self.label_style)
        self.lbl_nombre.pack(anchor=tk.W, pady=(10,0))
        self.ent_nombre = tk.Entry(self.form_frame, textvariable=self.var_nombre, **self.entry_style)
        self.ent_nombre.pack(pady=5)

        tk.Label(self.form_frame, text="Precio (Solo números):", **self.label_style).pack(anchor=tk.W, pady=(10,0))
        tk.Entry(self.form_frame, textvariable=self.var_precio, **self.entry_style).pack(pady=5)

        self.lbl_cat = tk.Label(self.form_frame, text="Tipo de Producto:", **self.label_style)
        self.lbl_cat.pack(anchor=tk.W, pady=(10,0))
        self.cb_cat = ttk.Combobox(self.form_frame, textvariable=self.var_cat, values=["pizzas", "bebidas", "ingredientes", "promociones", "base", "acompañamientos"], font=("Arial", 14), width=33, state="readonly")
        self.cb_cat.pack(pady=5)

        self.lbl_desc = tk.Label(self.form_frame, text="Ingredientes / Descripción:", **self.label_style)
        self.lbl_desc.pack(anchor=tk.W, pady=(10,0))
        self.txt_desc = tk.Text(self.form_frame, height=4, width=35, font=("Arial", 12))
        self.txt_desc.pack(pady=5)

        self.chk_disp = tk.Checkbutton(self.form_frame, text="¿ESTÁ DISPONIBLE PARA LA VENTA?", variable=self.var_disp, bg="#222", fg="#00FF00", font=("Arial", 12, "bold"), selectcolor="#1a1a1a")
        self.chk_disp.pack(pady=20)

        self.lbl_combo2 = tk.Label(self.form_frame, text="PIZZAS DISPONIBLES EN PROMOCIÓN (2 FAMILIARES + BEBIDA):", **self.label_style)
        self.list_combo2 = tk.Listbox(self.form_frame, selectmode=tk.MULTIPLE, height=10, width=35, font=("Arial", 12), bg="#111", fg="white", selectbackground="#FF0000", selectforeground="white")

        # Botones finales
        btns_final = tk.Frame(self.form_frame, bg="#222")
        btns_final.pack(pady=10)

        tk.Button(btns_final, text="💾 GUARDAR CAMBIOS", command=self.guardar_producto, bg="#00FF00", fg="black", font=("Arial", 14, "bold"), width=20, height=2).pack(side=tk.LEFT, padx=5)
        tk.Button(btns_final, text="✖ CANCELAR / VOLVER", command=lambda: self.form_frame.pack_forget(), bg="#555", fg="black", font=("Arial", 12, "bold"), width=18, height=2).pack(side=tk.LEFT, padx=5)
        self.btn_borrar = tk.Button(btns_final, text="🗑️ BORRAR", command=self.eliminar_producto, bg="#FF0000", fg="black", font=("Arial", 12, "bold"), width=10, height=2)
        self.btn_borrar.pack(side=tk.LEFT, padx=5)

        self.refrescar_lista_combo()
        self.form_frame.pack_forget() # Ocultar hasta elegir algo

    def refrescar_lista_combo(self):
        try:
            print(f"DEBUG: Consultando productos para sucursal: '{self.sucursal_activa}'")
            # Forzar recarga con timestamp para evitar caché
            res = requests.get(f"{API_URL}/admin/productos/todos?t={tk.IntVar().get()}", headers=self._headers())
            if res.status_code == 200:
                todos = res.json()
                self.todos_productos = todos
                
                target_suc = self.sucursal_activa.strip().lower()
                target_cat = self.cb_filtro_cat.get().strip().lower()
                if target_cat == "mitades":
                    self.combo_productos.pack_forget()
                    self.btn_nuevo.pack_forget()
                    self.var_id.set("")
                    self.var_nombre.set("")
                    self.var_precio.set("")
                    self.var_cat.set("pizzas")
                    self.var_disp.set(True)
                    self.txt_desc.delete("1.0", tk.END)
                    self.lbl_nombre.pack_forget()
                    self.ent_nombre.pack_forget()
                    self.lbl_cat.pack_forget()
                    self.cb_cat.pack_forget()
                    self.lbl_desc.pack_forget()
                    self.txt_desc.pack_forget()
                    self.chk_disp.pack_forget()
                    self.btn_borrar.pack_forget()
                    self.lbl_combo2.config(text="PIZZAS DISPONIBLES PARA MITADES:")
                    self.lbl_combo2.pack(anchor=tk.W, pady=(0, 5))
                    self.list_combo2.pack(pady=(0, 15))
                    self._cargar_pizzas_mitades()
                    self.form_frame.pack(fill=tk.BOTH, expand=True, pady=30)
                else:
                    if not self.combo_productos.winfo_ismapped():
                        self.combo_productos.pack(side=tk.LEFT, padx=10)
                    if not self.btn_nuevo.winfo_ismapped():
                        self.btn_nuevo.pack(side=tk.LEFT, padx=10)
                
                nuevos_productos = []
                for p in todos:
                    p_suc = str(p.get('sucursal', '')).strip().lower()
                    p_cat = str(p.get('categoria', '')).strip().lower()
                    
                    # Filtro por sucursal
                    match_suc = (p_suc == target_suc or p_suc.replace('_', ' ') == target_suc.replace('_', ' '))
                    # Filtro por categoría
                    match_cat = (p_cat == target_cat)
                    
                    if match_suc and match_cat:
                        nuevos_productos.append(p)
                
                # Actualizar lista siempre para reflejar el cambio de categoría
                if target_cat != "mitades":
                    self.productos_lista = nuevos_productos
                    nombres = sorted([p['nombre'] for p in self.productos_lista])
                    self.combo_productos['values'] = nombres
                
                # Resetear selección si cambiamos de categoría y el producto actual no pertenece
                if target_cat != "mitades":
                    actual_sel = self.combo_productos.get()
                    if not self.modo_nuevo and actual_sel not in nombres:
                        self.combo_productos.set(f"--- Elige una {self.cb_filtro_cat.get()} ---")
                        self.form_frame.pack_forget()
                
            # AUTO-RECARGA cada 10 segundos
            self.after_id = self.root.after(10000, self.refrescar_lista_combo)
            
        except Exception as e:
            print(f"Error de auto-recarga: {e}")
            self.after_id = self.root.after(10000, self.refrescar_lista_combo)

    def _match_sucursal(self, p_suc: str, target_suc: str) -> bool:
        p_suc = (p_suc or "").strip().lower()
        target_suc = (target_suc or "").strip().lower()
        if p_suc == target_suc:
            return True
        return p_suc.replace('_', ' ') == target_suc.replace('_', ' ')

    def _cargar_pizzas_combo2(self):
        self.list_combo2.delete(0, tk.END)
        pizzas = []
        for p in self.todos_productos:
            if not self._match_sucursal(str(p.get('sucursal', '')), self.sucursal_activa):
                continue
            cat = str(p.get('categoria', '')).strip().lower()
            if cat not in ("pizzas", "pizzas-familiares"):
                continue
            pizzas.append(p)
        pizzas.sort(key=lambda x: str(x.get('nombre', '')).upper())
        self._combo2_pizzas = pizzas
        for p in pizzas:
            self.list_combo2.insert(tk.END, str(p.get('nombre', '')).upper())
        for idx, p in enumerate(pizzas):
            if p.get('combo2_disponible', True):
                self.list_combo2.selection_set(idx)

    def _guardar_pizzas_combo2(self):
        if not hasattr(self, "_combo2_pizzas"):
            return
        seleccion = set(self.list_combo2.curselection())
        for idx, p in enumerate(self._combo2_pizzas):
            combo2_disp = idx in seleccion
            payload = {
                "nombre": str(p.get("nombre", "")).upper(),
                "precio": int(p.get("precio", 0) or 0),
                "categoria": str(p.get("categoria", "")).strip().lower(),
                "sucursal": p.get("sucursal", self.sucursal_activa),
                "descripcion": p.get("descripcion") or "",
                "disponible": bool(p.get("disponible", True)),
                "combo2_disponible": combo2_disp,
            }
            try:
                requests.put(f"{API_URL}/admin/productos/{p.get('id')}", json=payload, timeout=10, headers=self._headers())
            except Exception:
                pass

    def _cargar_pizzas_mitades(self):
        self.list_combo2.delete(0, tk.END)
        pizzas = []
        for p in self.todos_productos:
            if not self._match_sucursal(str(p.get('sucursal', '')), self.sucursal_activa):
                continue
            cat = str(p.get('categoria', '')).strip().lower()
            if cat not in ("pizzas", "pizzas-familiares"):
                continue
            pizzas.append(p)
        pizzas.sort(key=lambda x: str(x.get('nombre', '')).upper())
        self._mitades_pizzas = pizzas
        for p in pizzas:
            self.list_combo2.insert(tk.END, str(p.get('nombre', '')).upper())
        for idx, p in enumerate(pizzas):
            if p.get('mitades_disponible', True):
                self.list_combo2.selection_set(idx)

    def _guardar_pizzas_mitades(self):
        if not hasattr(self, "_mitades_pizzas"):
            return
        seleccion = set(self.list_combo2.curselection())
        for idx, p in enumerate(self._mitades_pizzas):
            mitades_disp = idx in seleccion
            payload = {
                "nombre": str(p.get("nombre", "")).upper(),
                "precio": int(p.get("precio", 0) or 0),
                "categoria": str(p.get("categoria", "")).strip().lower(),
                "sucursal": p.get("sucursal", self.sucursal_activa),
                "descripcion": p.get("descripcion") or "",
                "disponible": bool(p.get("disponible", True)),
                "mitades_disponible": mitades_disp,
            }
            try:
                requests.put(f"{API_URL}/admin/productos/{p.get('id')}", json=payload, timeout=10, headers=self._headers())
            except Exception:
                pass

    def seleccionar_producto_combo(self, event):
        self.modo_nuevo = False
        nombre_sel = self.combo_productos.get()
        # Buscamos el producto exacto por nombre en nuestra lista filtrada
        prod = next((p for p in self.productos_lista if p['nombre'] == nombre_sel), None)
        
        if prod:
            # Limpiar y cargar datos
            self.var_id.set(prod['id'])
            self.var_nombre.set(prod['nombre'])
            self.var_precio.set(prod['precio'])
            
            # Asegurar que la categoría se seleccione correctamente en el combo
            cat_actual = str(prod['categoria']).strip().lower()
            if cat_actual in self.cb_cat['values']:
                self.cb_cat.set(cat_actual)
            else:
                self.cb_cat.set("pizzas")
                
            self.var_disp.set(prod['disponible'])
            
            # Cargar descripción
            self.txt_desc.delete("1.0", tk.END)
            desc = prod.get('descripcion')
            self.txt_desc.insert("1.0", str(desc) if desc else "")
            
            # MOSTRAR FORMULARIO
            self.form_frame.pack(fill=tk.BOTH, expand=True, pady=30)
            self.btn_borrar.pack(side=tk.LEFT, padx=5)

            # SI ES CATEGORÍA "BASE" O "PROMOCIONES"
            # SOLO MOSTRAMOS EL PRECIO Y DISPONIBILIDAD PARA NO COMPLICAR
            if cat_actual in ["base", "promociones"]:
                self.lbl_nombre.pack_forget()
                self.ent_nombre.pack_forget()
                self.lbl_cat.pack_forget()
                self.cb_cat.pack_forget()
                self.lbl_desc.pack_forget()
                self.txt_desc.pack_forget()
                # El botón borrar también lo ocultamos para estas categorías
                self.btn_borrar.pack_forget()
                if cat_actual == "promociones":
                    self.lbl_combo2.pack(anchor=tk.W, pady=(0, 5))
                    self.list_combo2.pack(pady=(0, 15))
                    self._cargar_pizzas_combo2()
                else:
                    self.lbl_combo2.pack_forget()
                    self.list_combo2.pack_forget()
            else:
                # Mostrar todo de nuevo si no es base
                self.lbl_nombre.pack(anchor=tk.W, pady=(10,0))
                self.ent_nombre.pack(pady=5)
                self.lbl_cat.pack(anchor=tk.W, pady=(10,0))
                self.cb_cat.pack(pady=5)
                self.lbl_desc.pack(anchor=tk.W, pady=(10,0))
                self.txt_desc.pack(pady=5)
                self.btn_borrar.pack(side=tk.LEFT, padx=5)
                self.lbl_combo2.pack_forget()
                self.list_combo2.pack_forget()
        else:
            print(f"DEBUG: No se encontró información para '{nombre_sel}'")

    def preparar_nuevo_producto(self):
        self.modo_nuevo = True
        self.var_id.set("")
        self.var_nombre.set("")
        self.var_precio.set("")
        self.var_cat.set("pizzas")
        self.var_disp.set(True)
        self.txt_desc.delete("1.0", tk.END)
        self.combo_productos.set("NUEVO PRODUCTO")
        
        # Mostrar todo en el formulario
        self.lbl_nombre.pack(anchor=tk.W, pady=(10,0))
        self.ent_nombre.pack(pady=5)
        self.lbl_cat.pack(anchor=tk.W, pady=(10,0))
        self.cb_cat.pack(pady=5)
        self.lbl_desc.pack(anchor=tk.W, pady=(10,0))
        self.txt_desc.pack(pady=5)
        
        self.btn_borrar.pack_forget() # No se puede borrar algo que no existe
        self.lbl_combo2.pack_forget()
        self.list_combo2.pack_forget()
        self.form_frame.pack(fill=tk.BOTH, expand=True, pady=30)

    def guardar_producto(self):
        if self.cb_filtro_cat.get().strip().lower() == "mitades":
            self._guardar_pizzas_mitades()
            messagebox.showinfo("Listo", "Mitades actualizado")
            return
        if not self.var_nombre.get() or not self.var_precio.get():
            messagebox.showwarning("Atención", "Escribe el NOMBRE y el PRECIO")
            return
        
        data = {
            "nombre": self.var_nombre.get().upper(),
            "precio": int(self.var_precio.get()),
            "categoria": self.var_cat.get(),
            "sucursal": self.sucursal_activa,
            "descripcion": self.txt_desc.get("1.0", tk.END).strip(),
            "disponible": self.var_disp.get()
        }
        
        try:
            if self.var_id.get():
                res = requests.put(f"{API_URL}/admin/productos/{self.var_id.get()}", json=data, headers=self._headers())
            else:
                res = requests.post(f"{API_URL}/admin/productos", json=data, headers=self._headers())
            
            if res.status_code == 200:
                if self.var_cat.get().strip().lower() == "promociones":
                    self._guardar_pizzas_combo2()
                messagebox.showinfo("Listo", "¡Guardado con éxito!")
                self.modo_nuevo = False
                self.refrescar_lista_combo()
                self.form_frame.pack_forget()
        except:
            messagebox.showerror("Error", "No se pudo guardar")

    def eliminar_producto(self):
        if messagebox.askyesno("Confirmar", "¿Seguro que quieres BORRAR este producto?"):
            try:
                requests.delete(f"{API_URL}/admin/productos/{self.var_id.get()}", headers=self._headers())
                messagebox.showinfo("Listo", "Producto eliminado")
                self.refrescar_lista_combo()
                self.form_frame.pack_forget()
            except:
                messagebox.showerror("Error", "No se pudo eliminar")

    def abrir_gestion_usuarios(self):
        self.limpiar_pantalla()
        header = tk.Frame(self.root, bg="#333", height=70)
        header.pack(fill=tk.X)
        tk.Button(header, text="ATRÁS", command=self.mostrar_menu_principal, bg="black", fg="black", font=("Arial", 12, "bold"), width=10).pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(header, text="GESTIÓN DE USUARIOS", fg="white", bg="#333", font=("Arial", 20, "bold")).pack(side=tk.LEFT, padx=100)

        scroll_wrap, scroll_inner = self._scroll_container(self.root)
        scroll_wrap.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        content = tk.Frame(scroll_inner, bg="#1a1a1a")
        content.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)

        # Lista simple
        tk.Label(content, text="Usuarios actuales:", font=("Arial", 12, "bold"), fg="white", bg="#1a1a1a").pack(anchor=tk.W)
        self.tree_user = ttk.Treeview(content, columns=("id", "nombre", "rol"), show="headings", height=5)
        self.tree_user.heading("id", text="ID"); self.tree_user.heading("nombre", text="NOMBRE"); self.tree_user.heading("rol", text="ROL")
        self.tree_user.pack(fill=tk.X, pady=10)

        # Formulario usuario
        u_frame = tk.Frame(content, bg="#222", padx=20, pady=20)
        u_frame.pack(fill=tk.X, pady=20)

        self.u_nom = tk.StringVar(); self.u_mail = tk.StringVar(); self.u_pass = tk.StringVar()
        
        tk.Label(u_frame, text="Nombre:", bg="#222", fg="white").pack()
        tk.Entry(u_frame, textvariable=self.u_nom, font=("Arial", 14), width=30).pack(pady=5)
        
        tk.Label(u_frame, text="Email/Usuario:", bg="#222", fg="white").pack()
        tk.Entry(u_frame, textvariable=self.u_mail, font=("Arial", 14), width=30).pack(pady=5)
        
        tk.Label(u_frame, text="Clave:", bg="#222", fg="white").pack()
        tk.Entry(u_frame, textvariable=self.u_pass, font=("Arial", 14), width=30, show="*").pack(pady=5)

        tk.Button(u_frame, text="➕ CREAR NUEVO USUARIO", command=self.crear_usuario, bg="#00FF00", fg="black", font=("Arial", 12, "bold"), height=2).pack(pady=20)
        tk.Button(content, text="❌ ELIMINAR SELECCIONADO", command=self.eliminar_usuario, bg="#FF0000", fg="black", font=("Arial", 10, "bold")).pack()

        self.refrescar_usuarios()

    def refrescar_usuarios(self):
        for i in self.tree_user.get_children(): self.tree_user.delete(i)
        try:
            res = requests.get(f"{API_URL}/admin/usuarios", headers=self._headers())
            if res.status_code == 200:
                for u in res.json():
                    self.tree_user.insert("", tk.END, values=(u['id'], u['nombre'], u['rol']))
        except: pass

    def crear_usuario(self):
        data = {"nombre": self.u_nom.get(), "email": self.u_mail.get(), "password": self.u_pass.get(), "rol": "admin"}
        try:
            requests.post(f"{API_URL}/admin/usuarios", json=data, headers=self._headers())
            messagebox.showinfo("Listo", "Usuario creado")
            self.refrescar_usuarios()
        except: pass

    def eliminar_usuario(self):
        sel = self.tree_user.selection()
        if not sel: return
        uid = self.tree_user.item(sel[0])['values'][0]
        if messagebox.askyesno("Confirmar", "¿Borrar usuario?"):
            requests.delete(f"{API_URL}/admin/usuarios/{uid}", headers=self._headers())
            self.refrescar_usuarios()

    def abrir_cierre_locales(self):
        self.limpiar_pantalla()
        header = tk.Frame(self.root, bg="#333", height=70)
        header.pack(fill=tk.X)
        tk.Button(header, text="ATRÁS", command=self.mostrar_menu_principal, bg="black", fg="black", font=("Arial", 12, "bold"), width=10).pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(header, text="CIERRE DE LOCALES", fg="white", bg="#333", font=("Arial", 20, "bold")).pack(side=tk.LEFT, padx=100)

        content = tk.Frame(self.root, bg="#1a1a1a")
        content.pack(fill=tk.BOTH, expand=True, padx=50, pady=20)

        filas = [
            ("La Serena", "la_serena"),
            ("Coquimbo", "coquimbo"),
        ]
        self.cierre_vars = {}
        self.horario_vars = {}
        for nombre, slug in filas:
            fila = tk.Frame(content, bg="#222", padx=20, pady=15)
            fila.pack(fill=tk.X, pady=10)
            tk.Label(fila, text=nombre, fg="#ffffff", bg="#222", font=("Arial", 16, "bold")).pack(side=tk.LEFT)
            var = tk.StringVar(value="desconocido")
            self.cierre_vars[slug] = var
            estado_lbl = tk.Label(fila, textvariable=var, fg="#FFD700", bg="#222", font=("Arial", 14, "bold"))
            estado_lbl.pack(side=tk.LEFT, padx=20)
            def make_toggle(s):
                return lambda: self.toggle_cierre(s)
            tk.Button(fila, text="Cambiar estado", command=make_toggle(slug), bg="#FF0000", fg="black", font=("Arial", 12, "bold")).pack(side=tk.RIGHT)

            horarios = tk.Frame(content, bg="#222", padx=20, pady=12)
            horarios.pack(fill=tk.X, pady=(0, 12))
            tk.Label(horarios, text="Día", fg="#ffffff", bg="#222", font=("Arial", 11, "bold"), width=10, anchor="w").grid(row=0, column=0, sticky="w")
            tk.Label(horarios, text="Apertura", fg="#ffffff", bg="#222", font=("Arial", 11, "bold"), width=10, anchor="w").grid(row=0, column=1, sticky="w")
            tk.Label(horarios, text="Cierre", fg="#ffffff", bg="#222", font=("Arial", 11, "bold"), width=10, anchor="w").grid(row=0, column=2, sticky="w")

            dias = [
                ("Lunes", "mon"),
                ("Martes", "tue"),
                ("Miércoles", "wed"),
                ("Jueves", "thu"),
                ("Viernes", "fri"),
                ("Sábado", "sat"),
                ("Domingo", "sun"),
            ]
            self.horario_vars[slug] = {}
            for idx, (label, key) in enumerate(dias, start=1):
                tk.Label(horarios, text=label, fg="#ffffff", bg="#222", font=("Arial", 10, "bold"), width=10, anchor="w").grid(row=idx, column=0, sticky="w", pady=2)
                v_open = tk.StringVar(value="")
                v_close = tk.StringVar(value="")
                tk.Entry(horarios, textvariable=v_open, width=6, justify="center").grid(row=idx, column=1, sticky="w", padx=(0, 10))
                tk.Entry(horarios, textvariable=v_close, width=6, justify="center").grid(row=idx, column=2, sticky="w")
                self.horario_vars[slug][key] = (v_open, v_close)

            def make_save(s):
                return lambda: self.guardar_horario(s)
            tk.Button(horarios, text="Guardar horario", command=make_save(slug), bg="#00FF00", fg="black", font=("Arial", 11, "bold")).grid(row=1, column=3, rowspan=2, padx=(20, 0), sticky="n")

        tk.Button(content, text="Actualizar estados", command=self.cargar_estados_cierre, bg="#00FF00", fg="black", font=("Arial", 12, "bold")).pack(pady=10)
        self.cargar_estados_cierre()

    def cargar_estados_cierre(self):
        try:
            for slug in ["la_serena", "coquimbo"]:
                r = requests.get(f"{API_URL}/config/{slug}", headers=self._headers(), timeout=10)
                if r.status_code == 200:
                    dat = r.json()
                    self.cierre_vars[slug].set("abierto" if (dat.get("cerrado") is not True) else "cerrado")
                    def fmt(m):
                        try:
                            if m is None:
                                return ""
                            m = int(m)
                            hh = m // 60
                            mm = m % 60
                            return f"{hh:02d}:{mm:02d}"
                        except Exception:
                            return ""
                    if slug in self.horario_vars:
                        horario = dat.get("horario_semanal")
                        if not isinstance(horario, dict) or not horario:
                            reg_o = dat.get("open_regular_min", 810)
                            reg_c = dat.get("close_regular_min", 1375)
                            we_o = dat.get("open_weekend_min", 810)
                            we_c = dat.get("close_weekend_min", 1420)
                            horario = {
                                "mon": {"open": reg_o, "close": reg_c},
                                "tue": {"open": reg_o, "close": reg_c},
                                "wed": {"open": reg_o, "close": reg_c},
                                "thu": {"open": reg_o, "close": reg_c},
                                "fri": {"open": we_o, "close": we_c},
                                "sat": {"open": we_o, "close": we_c},
                                "sun": {"open": reg_o, "close": reg_c},
                            }
                        for day_key, (v_open, v_close) in self.horario_vars[slug].items():
                            d = horario.get(day_key) or {}
                            v_open.set(fmt(d.get("open")))
                            v_close.set(fmt(d.get("close")))
                else:
                    self.cierre_vars[slug].set("error")
        except Exception:
            for slug in ["la_serena", "coquimbo"]:
                self.cierre_vars[slug].set("error")

    def toggle_cierre(self, sucursal_slug):
        try:
            getr = requests.get(f"{API_URL}/config/{sucursal_slug}", headers=self._headers(), timeout=10)
            cur_cerrado = False
            if getr.status_code == 200:
                cur_cerrado = bool(getr.json().get("cerrado"))
            body = {"cerrado": (not cur_cerrado)}
            upr = requests.put(f"{API_URL}/config/{sucursal_slug}", json=body, headers=self._headers(), timeout=10)
            if upr.status_code == 200:
                self.cargar_estados_cierre()
                messagebox.showinfo("Listo", f"{sucursal_slug.replace('_',' ').title()}: estado actualizado")
            else:
                messagebox.showerror("Error", "No se pudo actualizar estado")
        except Exception:
            messagebox.showerror("Error", "No hay conexión con el servidor")

    def guardar_horario(self, sucursal_slug):
        try:
            day_vars = self.horario_vars.get(sucursal_slug)
            if not day_vars:
                return
            schedule = {}
            for day_key, (v_open, v_close) in day_vars.items():
                schedule[day_key] = {"open": v_open.get().strip(), "close": v_close.get().strip()}
            r = requests.put(f"{API_URL}/config/{sucursal_slug}", json={"schedule": schedule}, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                messagebox.showinfo("Listo", "Horario actualizado")
                self.cargar_estados_cierre()
            elif r.status_code == 401:
                messagebox.showerror("No autorizado", "Token inválido o faltante. Revisa ADMIN_API_TOKEN en este PC.")
            else:
                messagebox.showerror("Error", "No se pudo actualizar el horario (formato HH:MM)")
        except Exception:
            messagebox.showerror("Error", "No hay conexión con el servidor")
if __name__ == "__main__":
    root = tk.Tk()
    app = AdminManager(root)
    root.mainloop()
