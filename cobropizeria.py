import os
import subprocess
from decimal import Decimal, ROUND_HALF_UP
import tkinter as tk
from tkinter import ttk, messagebox
import threading


MESES_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def _env(name, default=""):
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def _run_psql(query: str) -> str:
    database_url = _env("DATABASE_URL", "")
    if database_url:
        if database_url.startswith("http://") or database_url.startswith("https://"):
            raise RuntimeError("DATABASE_URL debe ser una URL de Postgres (postgres:// o postgresql://), no una URL de la API")
        cmd = ["psql", database_url, "-At", "-F", ",", "-c", query]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            msg = proc.stderr.strip() or "Error ejecutando psql"
            raise RuntimeError(msg)
        return proc.stdout.strip()

    user = _env("DB_USER", _env("PGUSER", "macbook"))
    host = _env("DB_HOST", _env("PGHOST", "localhost"))
    dbname = _env("DB_NAME", _env("PGDATABASE", "pizzeria_db"))
    port = _env("DB_PORT", _env("PGPORT", "5432"))
    password = _env("DB_PASSWORD", _env("PGPASSWORD", ""))

    env = os.environ.copy()
    env["PGUSER"] = user
    env["PGHOST"] = host
    env["PGDATABASE"] = dbname
    env["PGPORT"] = str(port)
    if password:
        env["PGPASSWORD"] = password

    cmd = ["psql", "-At", "-F", ",", "-c", query]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or "Error ejecutando psql"
        raise RuntimeError(msg)
    return proc.stdout.strip()


def _money(n: Decimal) -> str:
    q = n.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"${q:,}".replace(",", ".")


def _fetch_monthly_rows():
    query = (
        "SELECT to_char((fecha AT TIME ZONE 'America/Santiago')::date, 'YYYY-MM') AS mes, "
        "COALESCE(SUM(total), 0) AS total_mes "
        "FROM pedidos "
        "WHERE estado = 'pagado' "
        "GROUP BY 1 "
        "ORDER BY 1;"
    )
    out = _run_psql(query)
    return [line.split(",", 1) for line in out.splitlines() if line.strip()]


def _build_rows(rows):
    built = []
    for mes, total_mes in rows:
        ventas = Decimal(total_mes or "0")
        porcentaje_1 = ventas * Decimal("0.01")
        iva_19 = porcentaje_1 * Decimal("0.19")
        cobro_total = porcentaje_1 + iva_19
        built.append((mes, ventas, porcentaje_1, iva_19, cobro_total))
    return built


def _mes_display(yyyy_mm: str) -> str:
    year, month = yyyy_mm.split("-", 1)
    m = int(month)
    return f"{MESES_ES.get(m, yyyy_mm)} {year}"


class CobroPizeriaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Cobro Pizeria - Resumen Mensual (1% + IVA)")
        self.root.geometry("920x560")
        self.root.configure(bg="#111")

        self.built_all = []
        self.mes_display_to_key = {}

        header = tk.Frame(self.root, bg="#333")
        header.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(
            header,
            text="COBRO PIZERIA (VENTAS Y COBRO 1% + IVA POR MES)",
            font=("Arial", 16, "bold"),
            fg="#ffffff",
            bg="#333",
        ).pack(side=tk.LEFT, padx=10, pady=10)

        self.btn_cargar = tk.Button(
            header,
            text="CARGAR",
            command=self.cargar,
            bg="#00FF00",
            fg="black",
            font=("Arial", 11, "bold"),
            width=12,
            height=2,
        )
        self.btn_cargar.pack(side=tk.RIGHT, padx=10, pady=10)

        filtro = tk.Frame(self.root, bg="#111")
        filtro.pack(fill=tk.X, padx=15, pady=(0, 10))

        tk.Label(
            filtro,
            text="MES:",
            font=("Arial", 12, "bold"),
            fg="#ffffff",
            bg="#111",
        ).pack(side=tk.LEFT)

        self.mes_var = tk.StringVar(value="TODOS")
        self.combo_mes = ttk.Combobox(
            filtro,
            textvariable=self.mes_var,
            state="readonly",
            width=22,
            font=("Arial", 12),
            values=["TODOS"],
        )
        self.combo_mes.pack(side=tk.LEFT, padx=10)
        self.combo_mes.bind("<<ComboboxSelected>>", lambda e: self._aplicar_filtro())

        self.total_general_var = tk.StringVar(value="TOTAL VENTAS: $0 | COBRO (1% + IVA): $0")
        tk.Label(
            filtro,
            textvariable=self.total_general_var,
            font=("Arial", 12, "bold"),
            fg="#00FF00",
            bg="#111",
        ).pack(side=tk.RIGHT)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#222", foreground="white", fieldbackground="#222", rowheight=28)
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.map("Treeview", background=[("selected", "#FF0000")])

        cols = ("mes", "ventas", "porcentaje_1", "iva_19", "cobro_total")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")
        self.tree.heading("mes", text="MES")
        self.tree.heading("ventas", text="VENTAS")
        self.tree.heading("porcentaje_1", text="1%")
        self.tree.heading("iva_19", text="IVA 19% DEL 1%")
        self.tree.heading("cobro_total", text="COBRO TOTAL")
        self.tree.column("mes", width=140)
        self.tree.column("ventas", width=180, anchor=tk.E)
        self.tree.column("porcentaje_1", width=140, anchor=tk.E)
        self.tree.column("iva_19", width=160, anchor=tk.E)
        self.tree.column("cobro_total", width=180, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        footer = tk.Frame(self.root, bg="#111")
        footer.pack(fill=tk.X, padx=15, pady=(0, 15))

        tk.Button(
            footer,
            text="CERRAR",
            command=self.root.destroy,
            bg="#555",
            fg="black",
            font=("Arial", 11, "bold"),
            height=2,
            width=12,
        ).pack(side=tk.RIGHT)

        self.cargar()

    def _set_loading(self, is_loading: bool):
        self.btn_cargar.configure(state=tk.DISABLED if is_loading else tk.NORMAL)

    def cargar(self):
        self._set_loading(True)
        threading.Thread(target=self._cargar_bg, daemon=True).start()

    def _cargar_bg(self):
        try:
            rows = _fetch_monthly_rows()
            built = _build_rows(rows)
            self.root.after(0, lambda: self._set_data(built))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self._set_loading(False))

    def _set_data(self, built):
        self.built_all = built
        displays = []
        self.mes_display_to_key = {}
        for mes, *_ in built:
            disp = _mes_display(mes)
            displays.append(disp)
            self.mes_display_to_key[disp] = mes
        self.combo_mes.configure(values=["TODOS"] + displays)
        if self.mes_var.get() not in self.combo_mes["values"]:
            self.mes_var.set("TODOS")
        self._aplicar_filtro()

    def _aplicar_filtro(self):
        sel = self.mes_var.get()
        if sel == "TODOS":
            data = self.built_all
        else:
            key = self.mes_display_to_key.get(sel)
            data = [r for r in self.built_all if r[0] == key]
        self._pintar(data)

    def _pintar(self, built):
        for item in self.tree.get_children():
            self.tree.delete(item)

        total_ventas = Decimal("0")
        total_cobro = Decimal("0")
        for mes, ventas, porcentaje_1, iva_19, cobro_total in built:
            total_ventas += ventas
            total_cobro += cobro_total
            self.tree.insert("", tk.END, values=(mes, _money(ventas), _money(porcentaje_1), _money(iva_19), _money(cobro_total)))

        self.total_general_var.set(f"TOTAL VENTAS: {_money(total_ventas)} | COBRO (1% + IVA): {_money(total_cobro)}")
        self._set_loading(False)


if __name__ == "__main__":
    root = tk.Tk()
    app = CobroPizeriaApp(root)
    root.mainloop()
