# ODS Manager

Prosty menedżer usług w Pythonie (Tkinter) dla Windows. Skanuje podfoldery
`C:\Apps`, a dla każdej znalezionej aplikacji pozwala ją uruchomić / zatrzymać,
zrobić `git pull`, a także wywołać to wszystko **zdalnie przez SSH**. Na dole
okna jest zintegrowana konsola pokazująca output serwerów i komend.

---

## Spis treści

- [Wymagania](#wymagania)
- [Uruchomienie](#uruchomienie)
- [Jak wykrywane są aplikacje](#jak-wykrywane-są-aplikacje)
- [Okno i przyciski](#okno-i-przyciski)
- [Konsola (output + input)](#konsola-output--input)
- [Pull i deploy](#pull-i-deploy)
- [Zdalne sterowanie przez SSH](#zdalne-sterowanie-przez-ssh)
- [Pliki w projekcie](#pliki-w-projekcie)
- [Znane ograniczenia](#znane-ograniczenia)

---

## Wymagania

- **Windows** (menedżer używa `taskkill`, `CREATE_NO_WINDOW`, a dla `.ps1` — PowerShella).
- **Python 3** z Tkinter (Tkinter jest w standardowej instalacji Pythona dla Windows).
- **git** w `PATH` — potrzebny do przycisku *Pull* i akcji *deploy*.
- Do sterowania zdalnego: **OpenSSH Server** na serwerze (patrz niżej).

## Uruchomienie

Dwuklik na `run_manager_run.bat` (uruchamia `pythonw manager.py` bez okna konsoli),
albo z wiersza poleceń:

```bat
python manager.py
```

Zamknięcie okna krzyżykiem **minimalizuje** aplikację (usługi działają dalej).
Realne zamknięcie to przycisk *✕ Zakończ*.

## Jak wykrywane są aplikacje

Menedżer skanuje podfoldery katalogu `C:\Apps` (stała `APPS_DIR` w `manager.py`).
Pomija własny folder i foldery zaczynające się od kropki. Folder trafia na listę
tylko wtedy, gdy znajdzie w nim **plik startowy**.

**Priorytet pliku startowego** — najpierw wg nazwy, potem wg rozszerzenia:

- nazwy (malejąco): `uruchom_lan` → `uruchom` → `start` → *nazwa folderu*,
- rozszerzenia (malejąco): `.bat` → `.ps1` → `.exe`.

Pierwsze trafienie wygrywa, np. `uruchom_lan.ps1` pokona `uruchom.bat`, a
`uruchom_lan.bat` pokona wszystko inne.

**Port** jest wykrywany pomocniczo (do wyświetlenia): najpierw z
`.streamlit/config.toml`, potem z plików `*.py`, `*.toml`, `*.cfg`, `*.ini`
w głównym folderze aplikacji (szukany wzorzec `PORT`/`SERVER_PORT = ...`).
Brak portu pokazywany jest jako `–`.

## Okno i przyciski

Każdy wiersz aplikacji zawiera:

| Element | Znaczenie |
|---|---|
| ● kropka | czerwona = zatrzymana, zielona = działa |
| nazwa | nazwa folderu aplikacji |
| ścieżka (szaro, kursywą) | pełna ścieżka pliku startowego |
| port | wykryty port lub `–` |
| **Pull** | `git pull` w folderze aplikacji |
| **Start / Stop** | uruchom / zatrzymaj usługę |

Na dole przyciski globalne: *▶ Uruchom wszystkie*, *■ Zatrzymaj wszystkie*,
*✕ Zakończ*.

Uruchamianie: pliki `.ps1` są odpalane przez
`powershell -NoProfile -ExecutionPolicy Bypass -File ...`, pozostałe przez
powłokę. Procesy startują z ustawionym `PYTHONUNBUFFERED=1`, żeby ich output
pojawiał się w konsoli na bieżąco. Zatrzymanie to `taskkill /T /F /PID` (ubija
całe drzewo procesów).

## Konsola (output + input)

Panel na dole okna (można rozciągnąć okno w pionie) ma **karty**:

- **Wszystko** — zbiorczy strumień (domyślna karta): wszystkie serwery razem
  plus rzeczy nie-serwerowe (banner, status sterowania, output komend z linii
  wejścia),
- **po jednej karcie na każdy serwer** — tylko output danego serwera, dzięki
  czemu logi wielu usług się nie mieszają.

Linia danego serwera trafia jednocześnie na jego kartę **i** na „Wszystko". Każda
karta ma własne przewijanie, więc można czytać historię jednego serwera, gdy inny
pisze dalej. Do konsoli trafiają:

- **output uruchomionych serwerów** na żywo, z prefiksem `[nazwa_aplikacji]`,
- komunikaty menedżera: `▶ start:`, `■ stop:`, `⟳ git pull:`,
- wynik `git pull` (prefiks `[git:nazwa]`),
- output komend wpisanych w linię wejścia (tylko „Wszystko"),
- akcje zdalne (prefiks `[SSH]`).

**Linia wejścia** (`›` na samym dole) uruchamia komendy w powłoce w bieżącym
katalogu roboczym konsoli. Obsługiwane polecenia specjalne:

- `cls` / `clear` — czyści **aktywną kartę** (jest też przycisk *Wyczyść kartę*),
- `cd <ścieżka>` — zmienia katalog roboczy konsoli (zwykłe `cd` w komendzie się
  nie utrwala, bo każda komenda to osobna powłoka — dlatego `cd` jest osobno).

Każda karta ma bufor ograniczany do ~1000 linii. Zapisy do konsoli z wątków w tle
idą przez bezpieczną wątkowo kolejkę (Tkinter nie jest thread-safe).

## Pull i deploy

- **Pull** (przycisk) — `git pull` w folderze aplikacji, w wątku w tle (nie
  zamraża GUI). Ustawione `GIT_TERMINAL_PROMPT=0` (git nie wisi czekając na
  login — przy braku dostępu zwraca błąd) i **limit 120 s**. Wynik ląduje w konsoli.
- **Deploy** (tylko zdalnie, patrz niżej) = `git pull` **i po udanym pullu**
  `start`. Jeśli pull się nie powiedzie, start jest pomijany.

Informacje o remote i branchu bierze `.git` w folderze aplikacji — `git pull`
działa na aktualnym branchu z jego skonfigurowanym upstreamem.

## Zdalne sterowanie przez SSH

Cel: z innego komputera wpisać jedną komendę, która zrobi pull + start usługi na
serwerze. Komendy idą **przez działające okno menedżera** (więc widać je w
konsoli i aktualizują status).

### Architektura

- Działające GUI uruchamia **serwer sterujący na `127.0.0.1`** (domyślnie port
  `8787`), chroniony tokenem. Słucha tylko na pętli zwrotnej — **z sieci jest
  niewidoczny**.
- SSH jest tylko **uwierzytelnionym transportem** na serwer. Po zalogowaniu
  skrypt-klient ([ods_client.py](ods_client.py)) przekazuje żądanie do lokalnego
  endpointu z tokenem.
- Na zewnątrz wystawiony jest **tylko port SSH (22)**.

### Konfiguracja (`ods_control.json`)

Tworzy się automatycznie przy pierwszym uruchomieniu GUI, w folderze projektu:

```json
{ "host": "127.0.0.1", "port": 8787, "token": "<losowy>" }
```

Zawiera sekret (token) — jest w `.gitignore`, **nie commituj go**. Klient czyta
ten sam plik (albo plik wskazany zmienną `ODS_CONTROL_CFG`).

### Dostępne akcje

`list` · `status <app>` · `pull <app>` · `start <app>` · `stop <app>` ·
`deploy <app>` (= pull + start).

### Konfiguracja serwera (jednorazowo, jako administrator)

Jeśli serwer to inna maszyna niż ta z repo — skopiuj tam `manager.py` i
`ods_client.py`.

**1. Zainstaluj OpenSSH Server:**

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

**2. Utwórz zwykłe (NIE-administratorskie) konto** dla osoby zdalnej, np. `ods`:

```powershell
New-LocalUser -Name ods -FullName "ODS deploy" -Description "Zdalny deploy" -Password (Read-Host -AsSecureString "Haslo")
```

Konto musi mieć **odczyt** folderu projektu (żeby klient przeczytał
`ods_client.py` i `ods_control.json`). Nie dodawaj go do Administratorów — to celowe.

**3. Zainstaluj klucz publiczny z „forced command".** Osoba zdalna generuje
klucz u siebie (`ssh-keygen -t ed25519`) i przysyła plik `*.pub`. Na serwerze
utwórz `C:\Users\ods\.ssh\authorized_keys` z jedną linią (podmień ścieżkę
Pythona, ścieżkę projektu i klucz):

```text
restrict,command="C:\Windows\py.exe D:\claude\_ODS_Manager\ods_client.py" ssh-ed25519 AAAA...klucz... komentarz
```

`restrict` + `command=` sprawiają, że tym kluczem **nie da się zrobić nic poza**
wywołaniem klienta — bez powłoki, bez dostępu do plików, bez tuneli. Ustaw ACL
(Windows OpenSSH tego wymaga):

```powershell
icacls C:\Users\ods\.ssh\authorized_keys /inheritance:r /grant "ods:R" "SYSTEM:F" "Administrators:F"
```

> **Dlaczego konto musi być nie-administratorskie:** dla administratorów Windows
> OpenSSH ignoruje `authorized_keys` użytkownika i czyta wspólny
> `administrators_authorized_keys` — wtedy „forced command" by nie zadziałał.

### Jak wywołać (z komputera zdalnego)

Warunek: **okno menedżera jest uruchomione** na serwerze.

```bash
ssh -i sciezka\do\klucza ods@ADRES_SERWERA deploy NAZWA_APLIKACJI
```

Dla wygody można zrobić u siebie `ods.bat`:

```bat
@echo off
ssh -i %USERPROFILE%\.ssh\dominika_ods ods@ADRES_SERWERA %*
```

i wołać `ods deploy mojaapka`, `ods list`, `ods status mojaapka` itd.

**Szybki test lokalnie na serwerze** (gdy GUI działa), zanim ruszysz SSH:

```bat
py ods_client.py list
```

### Model bezpieczeństwa (skrót)

- Z sieci wystawiony tylko SSH (22); endpoint sterujący słucha wyłącznie na
  `127.0.0.1` + chroni go token.
- Klucz osoby zdalnej jest zamknięty do jednej komendy (forced command).
- Konto zdalne jest zwykłym (nie-admin) użytkownikiem.
- Klient dodatkowo pilnuje **białej listy akcji** i poprawności nazwy aplikacji.

## Pliki w projekcie

| Plik | Rola |
|---|---|
| `manager.py` | aplikacja GUI + serwer sterujący |
| `ods_client.py` | klient sterujący (uruchamiany przez SSH forced command) |
| `run_manager_run.bat` | wygodne uruchomienie GUI (`pythonw`) |
| `ods_control.json` | config endpointu z tokenem (generowany, **gitignore**) |
| `.gitignore` | ignoruje `ods_control.json` i `__pycache__` |

## Znane ograniczenia

- *✕ Zakończ* zamyka okno, ale **nie zatrzymuje** uruchomionych usług (mimo że
  komunikat to sugeruje) — usługi działają dalej jako osobne procesy.
- Zdalny `deploy` z nieudanym `git pull` zwraca komunikat tekstowy, ale kod
  wyjścia SSH to nadal 0 (odpowiedź HTTP 200) — do poprawy, jeśli potrzebne jest
  skryptowanie po kodzie wyjścia.
- `__pycache__` jest śledzony w repo od pierwszego commita; można go wypiąć
  (`git rm -r --cached __pycache__`).
