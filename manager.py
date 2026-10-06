"""
ODS Manager – prosty menedżer usług
Skanuje podfoldery C:\Apps i uruchamia/zatrzymuje aplikacje.
"""

import tkinter as tk
from tkinter import messagebox
import subprocess
import re
from pathlib import Path

APPS_DIR  = Path("C:/Apps")
SELF_DIR  = Path(__file__).parent.resolve()   # wyklucz własny folder niezależnie od nazwy
LAUNCHERS = ["uruchom_lan", "uruchom", "start"]  # priorytetowe nazwy pliku startowego (uruchom_lan ma pierwszeństwo)
EXTS      = (".bat", ".ps1", ".exe")             # dozwolone rozszerzenia, w kolejności priorytetu

# ── wykryj port aplikacji ─────────────────────────────────────
PORT_RE = re.compile(r"(?:SERVER_)?PORT\s*[=:]\s*[\"']?(\d{2,5})[\"']?", re.IGNORECASE)

def find_port(folder: Path):
    # 1. .streamlit/config.toml
    cfg = folder / ".streamlit" / "config.toml"
    if cfg.exists():
        m = PORT_RE.search(cfg.read_text(errors="ignore"))
        if m:
            return m.group(1)

    # 2. pliki .py i .toml w głównym folderze
    for ext in ("*.py", "*.toml", "*.cfg", "*.ini"):
        for f in folder.glob(ext):
            m = PORT_RE.search(f.read_text(errors="ignore"))
            if m:
                return m.group(1)

    return "–"

# ── znajdź plik startowy w folderze ──────────────────────────
def find_launcher(folder: Path):
    candidates = LAUNCHERS + [folder.name]
    for name in candidates:
        for ext in EXTS:
            f = folder / (name + ext)
            if f.exists():
                return f
    return None

# ── zbierz listę aplikacji ────────────────────────────────────
def discover_apps():
    apps = []
    for d in sorted(APPS_DIR.iterdir()):
        if not d.is_dir() or d.resolve() == SELF_DIR or d.name.startswith("."):
            continue
        launcher = find_launcher(d)
        if launcher:
            apps.append({"name": d.name, "dir": d, "launcher": launcher,
                         "port": find_port(d), "proc": None})
    return apps

# ── GUI ───────────────────────────────────────────────────────
BG      = "#1e1e2e"
ROW_A   = "#252535"
ROW_B   = "#1e1e2e"
FG      = "#cdd6f4"
GRAY    = "#6c7086"
GREEN   = "#a6e3a1"
RED     = "#f38ba8"
BTN_BG  = "#313244"
BTN_ACT = "#45475a"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ODS – Menedżer usług")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.iconify)   # X → minimalizuj
        self.apps = discover_apps()
        self.rows = []
        self._build()
        self._poll()

    def _build(self):
        tk.Label(self, text="ODS – Menedżer usług", bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold"), pady=10).pack(fill="x")

        frame = tk.Frame(self, bg=BG)
        frame.pack(padx=16, pady=(0, 10))

        for i, app in enumerate(self.apps):
            bg = ROW_A if i % 2 else ROW_B
            row = tk.Frame(frame, bg=bg, pady=6, padx=10)
            row.pack(fill="x", pady=1)

            dot = tk.Label(row, text="●", fg=RED, bg=bg, font=("Segoe UI", 14), width=2)
            dot.pack(side="left")

            tk.Label(row, text=app["name"], bg=bg, fg=FG,
                     font=("Segoe UI", 10), width=26, anchor="w").pack(side="left")

            # nazwa pliku startowego + ścieżka (szaro, kursywą)
            tk.Label(row, text=str(app["launcher"]), bg=bg, fg=GRAY,
                     font=("Segoe UI", 9, "italic"), anchor="w").pack(side="left")

            btn = tk.Button(row, text="Start", width=8,
                            bg=BTN_BG, fg=FG, relief="flat",
                            activebackground=BTN_ACT, activeforeground=FG,
                            font=("Segoe UI", 9),
                            command=lambda a=app, b=None: self._toggle(a))
            btn.pack(side="right", padx=(8, 0))

            tk.Label(row, text=app["port"], bg=bg, fg="#6e7a9a",
                     font=("Consolas", 9), width=6, anchor="e").pack(side="right", padx=(12, 0))

            self.rows.append({"dot": dot, "btn": btn, "app": app, "bg": bg})

        # ── przyciski globalne ────────────────────────────────
        bar = tk.Frame(self, bg=BG)
        bar.pack(pady=(0, 12))
        tk.Button(bar, text="▶  Uruchom wszystkie", bg=BTN_BG, fg=FG,
                  relief="flat", activebackground=BTN_ACT, activeforeground=FG,
                  font=("Segoe UI", 9), padx=10, pady=4,
                  command=self._start_all).pack(side="left", padx=6)
        tk.Button(bar, text="■  Zatrzymaj wszystkie", bg=BTN_BG, fg=FG,
                  relief="flat", activebackground=BTN_ACT, activeforeground=FG,
                  font=("Segoe UI", 9), padx=10, pady=4,
                  command=self._stop_all).pack(side="left", padx=6)
        tk.Button(bar, text="✕  Zakończ", bg="#4a1e2e", fg=RED,
                  relief="flat", activebackground="#6a2e3e", activeforeground=RED,
                  font=("Segoe UI", 9), padx=10, pady=4,
                  command=self._confirm_exit).pack(side="left", padx=6)

        # ── bind przycisków (musi być po stworzeniu rows) ────
        for r in self.rows:
            r["btn"].config(command=lambda row=r: self._toggle(row))

    def _running(self, app):
        p = app["proc"]
        return p is not None and p.poll() is None

    def _toggle(self, row):
        app = row["app"]
        if self._running(app):
            self._stop(app)
        else:
            self._start(app)
        self._refresh()

    def _start(self, app):
        if self._running(app):
            return
        launcher = app["launcher"]
        if launcher.suffix.lower() == ".ps1":
            # .ps1 nie uruchomi cmd – trzeba wprost przez PowerShell
            cmd, shell = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(launcher)], False)
        else:
            cmd, shell = str(launcher), True
        app["proc"] = subprocess.Popen(
            cmd,
            cwd=str(app["dir"]),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            shell=shell,
        )

    def _stop(self, app):
        p = app["proc"]
        if p:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            app["proc"] = None

    def _start_all(self):
        for r in self.rows:
            self._start(r["app"])
        self._refresh()

    def _stop_all(self):
        for r in self.rows:
            self._stop(r["app"])
        self._refresh()

    def _refresh(self):
        for r in self.rows:
            running = self._running(r["app"])
            r["dot"].config(fg=GREEN if running else RED)
            r["btn"].config(text="Stop" if running else "Start")

    def _confirm_exit(self):
        if messagebox.askokcancel(
            "Zamknij ODS Manager",
            "Zamknięcie tej aplikacji zakończy działanie szystkich uruchomionych usług."
        ):
            self.destroy()

    def _poll(self):
        self._refresh()
        self.after(3000, self._poll)


if __name__ == "__main__":
    App().mainloop()
