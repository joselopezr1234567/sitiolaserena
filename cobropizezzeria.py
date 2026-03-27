import os
import subprocess
from decimal import Decimal, ROUND_HALF_UP
import tkinter as tk
from tkinter import ttk, messagebox
import threading


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
        porcentaje_10 = ventas * Decimal("0.10")
        iva_10 = porcentaje_10 * Decimal("0.19")
        cobro_total = porcentaje_10 + iva_10
        built.append((mes, ventas, porcentaje_10, iva_10, cobro_total))
    return built

class CobroPizezzeriaApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Cobro Pizzería - Resumen Mensual (10% + IVA)")
        self.root.geometry("920x520")
        self.root.configure(bg="#111")

        header = tk.Frame(self.root, bg="#222")
        header.pack(fill=tk.X, padx=15, pady=15)

        tk.Label(
            header,
            text="COBRO PIZZERÍA (VENTAS Y COBRO 10% + IVA POR MES)",
            font=("Arial", 16, "bold"),
            fg="#FFD700",
            bg="#222",
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

        self.total_general_var = tk.StringVar(value="TOTAL VENTAS: $0 | COBRO (10% + IVA): $0")
        tk.Label(
            self.root,
            textvariable=self.total_general_var,
            font=("Arial", 14, "bold"),
            fg="#00FF00",
            bg="#111",
        ).pack(padx=15, pady=(0, 10), anchor=tk.E)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#222", foreground="white", fieldbackground="#222", rowheight=28)
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.map("Treeview", background=[("selected", "#FF0000")])

        cols = ("mes", "ventas", "porcentaje_10", "iva_10", "cobro_total")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")
        self.tree.heading("mes", text="MES")
        self.tree.heading("ventas", text="VENTAS")
        self.tree.heading("porcentaje_10", text="10%")
        self.tree.heading("iva_10", text="IVA 19% DEL 10%")
        self.tree.heading("cobro_total", text="COBRO TOTAL")
        self.tree.column("mes", width=110)
        self.tree.column("ventas", width=180, anchor=tk.E)
        self.tree.column("porcentaje_10", width=140, anchor=tk.E)
        self.tree.column("iva_10", width=160, anchor=tk.E)
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
            self.root.after(0, lambda: self._pintar(built))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self._set_loading(False))

    def _pintar(self, built):
        for item in self.tree.get_children():
            self.tree.delete(item)

        total_ventas = Decimal("0")
        total_cobro = Decimal("0")
        for mes, ventas, porcentaje_10, iva_10, cobro_total in built:
            total_ventas += ventas
            total_cobro += cobro_total
            self.tree.insert("", tk.END, values=(mes, _money(ventas), _money(porcentaje_10), _money(iva_10), _money(cobro_total)))

        self.total_general_var.set(f"TOTAL VENTAS: {_money(total_ventas)} | COBRO (10% + IVA): {_money(total_cobro)}")
        self._set_loading(False)


if __name__ == "__main__":
    root = tk.Tk()
    app = CobroPizezzeriaApp(root)
    root.mainloop()
