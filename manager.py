"""
ODS Manager – prosty menedżer usług
Skanuje podfoldery C:\Apps i uruchamia/zatrzymuje aplikacje.
"""

import tkinter as tk
from tkinter import messagebox, ttk
import subprocess
import re
import os
import threading
import queue
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
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

# ── zdalne sterowanie (localhost + token, transport przez SSH) ─
CONTROL_CFG = SELF_DIR / "ods_control.json"
ACTIONS     = {"deploy", "pull", "start", "stop", "status", "list"}

def load_control_cfg():
    # wczytaj config; uzupełnij brakujące pola (port, host, losowy token) i zapisz
    try:
        cfg = json.loads(CONTROL_CFG.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    changed = False
    for key, default in (("host", "127.0.0.1"), ("port", 8787)):
        if key not in cfg:
            cfg[key] = default; changed = True
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(24); changed = True
    if changed:
        try:
            CONTROL_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass
    return cfg

class _CtlHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):          # wycisz domyślne logi http.server
        pass

    def _send(self, code, text):
        body = text.encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        if self.headers.get("X-ODS-Token") != self.server.token:
            self._send(401, "401 – brak lub zły token")
            return
        u = urlparse(self.path)
        action = u.path.strip("/").lower()
        name = (parse_qs(u.query).get("app") or [""])[0]
        if action not in ACTIONS:
            self._send(400, f"nieznana akcja: {action}")
            return
        try:
            self._send(200, self.server.app.handle_remote(action, name))
        except KeyError:
            self._send(404, f"nieznana aplikacja: {name}")
        except Exception as e:
            self._send(500, f"błąd: {e}")

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
        self.resizable(False, True)        # pionowo można rozciągać (konsola)
        self.protocol("WM_DELETE_WINDOW", self.iconify)   # X → minimalizuj
        self.apps = discover_apps()
        self.rows = []
        self.console_cwd = SELF_DIR        # katalog roboczy wbudowanej konsoli
        self.ui_q = queue.Queue()          # kolejka GUI (wątki NIE dotykają Tk)
        self._lock = threading.Lock()      # chroni start/stop (GUI + zdalne naraz)
        self.ctl_srv = None
        self.ctl_port = None
        self._build()
        self._poll()
        self.log(f"Konsola gotowa. Katalog: {self.console_cwd}")
        self._drain()                      # pętla opróżniająca kolejkę do konsoli
        self._start_control()              # serwer sterujący (zdalne komendy)

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

            pull_btn = tk.Button(row, text="Pull", width=6,
                                 bg=BTN_BG, fg=FG, relief="flat",
                                 activebackground=BTN_ACT, activeforeground=FG,
                                 font=("Segoe UI", 9))
            pull_btn.config(command=lambda a=app, b=pull_btn: self._pull(a, b))
            pull_btn.pack(side="right", padx=(8, 0))

            tk.Label(row, text=app["port"], bg=bg, fg="#6e7a9a",
                     font=("Consolas", 9), width=6, anchor="e").pack(side="right", padx=(12, 0))

            self.rows.append({"dot": dot, "btn": btn, "pull": pull_btn, "app": app, "bg": bg})

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

        # ── konsola (output) – karty: Wszystko + po jednej na serwer ──
        con = tk.Frame(self, bg=BG)
        con.pack(fill="both", expand=True, padx=16, pady=(0, 6))

        head = tk.Frame(con, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Konsola", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "italic")).pack(side="left")
        tk.Button(head, text="Wyczyść kartę", bg=BTN_BG, fg=FG, relief="flat",
                  activebackground=BTN_ACT, activeforeground=FG,
                  font=("Segoe UI", 8), command=self._clear_console).pack(side="right")

        self._setup_tab_style()
        self.nb = ttk.Notebook(con)
        self.nb.pack(fill="both", expand=True, pady=(4, 0))

        self.consoles = {}          # nazwa aplikacji -> Text (karta serwera)
        self._tabs = []             # (klucz, ramka, Text) – do czyszczenia aktywnej
        self.console_all = self._add_console_tab("Wszystko")   # zbiorcza (pierwsza)
        for app in self.apps:
            self.consoles[app["name"]] = self._add_console_tab(app["name"])

        # ── linia wejścia (I/O) ───────────────────────────────
        cmd = tk.Frame(self, bg=BG)
        cmd.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(cmd, text="›", bg=BG, fg=GREEN,
                 font=("Consolas", 12, "bold")).pack(side="left", padx=(0, 6))
        self.cmd_var = tk.StringVar()
        self.cmd_entry = tk.Entry(cmd, textvariable=self.cmd_var, bg=ROW_A, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  font=("Consolas", 10))
        self.cmd_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.cmd_entry.bind("<Return>", self._run_cmd)
        tk.Button(cmd, text="▶", width=3, bg=BTN_BG, fg=FG, relief="flat",
                  activebackground=BTN_ACT, activeforeground=FG,
                  font=("Segoe UI", 9), command=self._run_cmd).pack(side="left", padx=(8, 0))

    def _setup_tab_style(self):
        # ciemny styl kart (ttk wymaga motywu "clam", żeby dało się je kolorować)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BTN_BG, foreground=GRAY,
                        padding=(10, 4), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BTN_ACT)],
                  foreground=[("selected", FG)])

    def _add_console_tab(self, title):
        frame = tk.Frame(self.nb, bg=BG)
        sb = tk.Scrollbar(frame)
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, height=12, bg="#11111b", fg=FG,
                      insertbackground=FG, relief="flat", wrap="word",
                      font=("Consolas", 9), yscrollcommand=sb.set, state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        self.nb.add(frame, text=title)
        self._tabs.append((title, frame, txt))
        return txt

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
        with self._lock:
            if self._running(app):
                return f"{app['name']}: już działa"
            launcher = app["launcher"]
            if launcher.suffix.lower() == ".ps1":
                # .ps1 nie uruchomi cmd – trzeba wprost przez PowerShell
                cmd, shell = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", str(launcher)], False)
            else:
                cmd, shell = str(launcher), True
            # PYTHONUNBUFFERED=1 → output np. Streamlita pojawia się od razu, nie w blokach
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            app["proc"] = subprocess.Popen(
                cmd,
                cwd=str(app["dir"]),
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                shell=shell, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
            )
            proc = app["proc"]
        self.log(f"▶ start: {app['name']}", app=app["name"])
        threading.Thread(target=self._reader, args=(app, proc), daemon=True).start()
        return f"{app['name']}: uruchomiono"

    def _stop(self, app):
        with self._lock:
            p = app["proc"]
            if not p:
                return f"{app['name']}: nie było uruchomione"
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            app["proc"] = None
        self.log(f"■ stop: {app['name']}", app=app["name"])
        return f"{app['name']}: zatrzymano"

    def _reader(self, app, proc):
        # strumieniuje output procesu serwera do konsoli (wątek w tle)
        for line in proc.stdout:
            self.log(line.rstrip("\n"), source=app["name"], app=app["name"])
        self.log(f"proces zakończony (kod {proc.poll()})",
                 source=app["name"], app=app["name"])

    # ── git pull / deploy ─────────────────────────────────────
    def _pull(self, app, btn):
        # pull w tle, żeby nie zamrażać GUI; przycisk na ten czas blokujemy
        btn.config(state="disabled", text="…")
        self.log(f"⟳ git pull: {app['name']}", app=app["name"])

        def work():
            self._do_pull(app)
            self.ui(lambda: btn.config(state="normal", text="Pull"))
        threading.Thread(target=work, daemon=True).start()

    def _do_pull(self, app):
        # właściwy pull (synchroniczny); loguje do konsoli; zwraca (ok, tekst)
        # GIT_TERMINAL_PROMPT=0 → git nie wisi czekając na login, tylko zwraca błąd
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            res = subprocess.run(
                ["git", "pull"],
                cwd=str(app["dir"]),
                capture_output=True, text=True, errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env, timeout=120,
            )
            ok = res.returncode == 0
            out = (res.stdout + res.stderr).strip() or "(brak komunikatu)"
        except FileNotFoundError:
            ok, out = False, "Nie znaleziono polecenia 'git' w PATH."
        except subprocess.TimeoutExpired:
            ok, out = False, "Przekroczono limit czasu (120 s) – pull przerwany."
        except Exception as e:
            ok, out = False, str(e)
        self.log(out, source=f"git:{app['name']}", app=app["name"])
        self.log(f"{'✓' if ok else '✗'} git pull {app['name']} — "
                 f"{'OK' if ok else 'błąd'}", app=app["name"])
        return ok, out

    def _deploy(self, app):
        # dla zdalnej komendy 'deploy': pull, a po udanym pullu start
        ok, out = self._do_pull(app)
        if not ok:
            return f"git pull NIEUDANY:\n{out}\n(start pominięty)"
        return f"git pull OK:\n{out}\n{self._start(app)}"

    # ── zdalne sterowanie (wołane z wątku serwera HTTP) ───────
    def _find_app(self, name):
        for a in self.apps:
            if a["name"].lower() == name.lower():
                return a
        return None

    def handle_remote(self, action, name):
        # używa tylko kolejki logów i subprocess – NIE dotyka widgetów Tk
        self.log(f"⇄ zdalnie: {action} {name}".rstrip(), source="SSH",
                 app=(name or None))
        if action == "list":
            return "\n".join(
                f"{a['name']}\t{a['port']}\t"
                f"{'RUNNING' if self._running(a) else 'stopped'}"
                for a in self.apps) or "(brak aplikacji)"
        app = self._find_app(name)
        if app is None:
            raise KeyError(name)
        if action == "status":
            return "RUNNING" if self._running(app) else "stopped"
        if action == "pull":
            return self._do_pull(app)[1]
        if action == "start":
            return self._start(app)
        if action == "stop":
            return self._stop(app)
        if action == "deploy":
            return self._deploy(app)
        raise ValueError(action)          # nie powinno zajść (walidacja w handlerze)

    def _start_control(self):
        cfg = load_control_cfg()
        try:
            srv = ThreadingHTTPServer((cfg["host"], cfg["port"]), _CtlHandler)
        except Exception as e:
            self.log(f"[sterowanie] NIE uruchomiono serwera ({cfg['host']}:{cfg['port']}): {e}")
            return
        srv.app = self
        srv.token = cfg["token"]
        self.ctl_srv = srv
        self.ctl_port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.log(f"[sterowanie] nasłuch {cfg['host']}:{self.ctl_port} "
                 f"— zdalne komendy (pull/start/stop/deploy) przez SSH")

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

    # ── konsola: output ───────────────────────────────────────
    def log(self, text, source=None, app=None):
        # bezpieczne z każdego wątku – tylko wkłada do kolejki, nie dotyka Tk.
        # app = nazwa serwera → trafia na jego kartę + zbiorczą; None → tylko zbiorcza
        line = f"[{source}] {text}\n" if source else f"{text}\n"
        self.ui_q.put(("log", app, line))

    def ui(self, fn):
        # wykonaj operację na widgetach w wątku GUI (zachowuje kolejność z logami)
        self.ui_q.put(("call", fn))

    def _drain(self):
        # jedyne miejsce, które dotyka konsoli – działa w wątku GUI
        buffers = {}                       # Text -> list[str], zapis zbiorczo

        def flush():
            for w, parts in buffers.items():
                if parts:
                    self._append("".join(parts), w)
            buffers.clear()

        try:
            while True:
                item = self.ui_q.get_nowait()
                if item[0] == "call":
                    flush()
                    item[1]()
                else:                      # ("log", app, line)
                    _, app, line = item
                    targets = [self.console_all]
                    w = self.consoles.get(app) if app else None
                    if w is not None:
                        targets.append(w)
                    for t in targets:
                        buffers.setdefault(t, []).append(line)
        except queue.Empty:
            pass
        flush()
        self.after(100, self._drain)

    def _append(self, line, widget):
        widget.config(state="normal")
        widget.insert("end", line)
        n = int(widget.index("end-1c").split(".")[0])
        if n > 1200:                                   # ogranicz bufor do ~1000 linii
            widget.delete("1.0", f"{n - 1000}.0")
        widget.see("end")
        widget.config(state="disabled")

    def _active_console(self):
        # Text aktualnie wybranej karty (do czyszczenia)
        try:
            sel = self.nb.select()
        except Exception:
            return self.console_all
        for _, frame, txt in self._tabs:
            if str(frame) == sel:
                return txt
        return self.console_all

    def _clear_console(self):
        w = self._active_console()
        w.config(state="normal")
        w.delete("1.0", "end")
        w.config(state="disabled")

    # ── konsola: input (I/O) ──────────────────────────────────
    def _run_cmd(self, event=None):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        self.cmd_var.set("")
        low = cmd.lower()
        if low in ("cls", "clear"):
            self._clear_console()
            return
        if low == "cd" or low.startswith("cd "):
            self._change_dir(cmd[2:].strip())
            return
        self.log(f"{self.console_cwd}› {cmd}")
        threading.Thread(target=self._cmd_worker, args=(cmd,), daemon=True).start()

    def _cmd_worker(self, cmd):
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(self.console_cwd), shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                self.log(line.rstrip("\n"))
            proc.wait()
            self.log(f"[zakończono, kod {proc.returncode}]")
        except Exception as e:
            self.log(f"[błąd] {e}")

    def _change_dir(self, path):
        if not path:
            self.log(str(self.console_cwd))
            return
        target = Path(path) if os.path.isabs(path) else self.console_cwd / path
        target = target.resolve()
        if target.is_dir():
            self.console_cwd = target
            self.log(f"[cwd] {target}")
        else:
            self.log(f"[błąd] nie ma katalogu: {target}")


if __name__ == "__main__":
    App().mainloop()
