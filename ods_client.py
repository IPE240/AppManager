#!/usr/bin/env python
"""
Klient sterujący ODS Managerem.

Wywoływany po stronie serwera (zwykle jako SSH "forced command"): odczytuje
żądaną akcję z $SSH_ORIGINAL_COMMAND (albo z argumentów przy wywołaniu lokalnym),
sprawdza ją względem białej listy i przekazuje do lokalnego endpointu menedżera
(127.0.0.1 + token). Dzięki temu klucz SSH Dominiki może WYŁĄCZNIE wywołać te
akcje – nie daje powłoki ani dostępu do plików.

Użycie:
    deploy <app> | pull <app> | start <app> | stop <app> | status <app> | list

Config brany z ods_control.json (ten sam folder), albo z pliku wskazanego przez
zmienną środowiskową ODS_CONTROL_CFG.
"""
import os
import re
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

ACTIONS = {"deploy", "pull", "start", "stop", "status", "list"}
CFG = Path(os.environ.get("ODS_CONTROL_CFG", Path(__file__).parent / "ods_control.json"))


def main():
    # akcja: z SSH_ORIGINAL_COMMAND (tryb SSH) albo z argv (tryb lokalny)
    raw = os.environ.get("SSH_ORIGINAL_COMMAND", "").strip()
    args = raw.split() if raw else sys.argv[1:]
    if not args:
        print("użycie: deploy|pull|start|stop|status <app>  |  list")
        return 2

    action = args[0].lower()
    name = args[1] if len(args) > 1 else ""
    if action not in ACTIONS:
        print(f"niedozwolona akcja: {action}")
        return 2
    if action != "list" and not name:
        print(f"akcja '{action}' wymaga nazwy aplikacji")
        return 2
    if name and not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        print("niedozwolona nazwa aplikacji")
        return 2

    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"nie można wczytać configu {CFG}: {e}")
        return 1

    url = f"http://{cfg.get('host', '127.0.0.1')}:{cfg['port']}/{action}"
    if name:
        url += "?app=" + urllib.parse.quote(name)
    req = urllib.request.Request(url, method="POST",
                                 headers={"X-ODS-Token": cfg["token"]})
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            print(r.read().decode("utf-8", "replace"))
            return 0
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace"))
        return 1
    except Exception as e:
        print(f"nie można połączyć z menedżerem ({url}): {e}")
        print("Czy okno ODS Managera jest uruchomione na serwerze?")
        return 1


if __name__ == "__main__":
    sys.exit(main())
