# COA Desktop — PyInstaller onedir

## Cel

Spakować `coa_app/` + `mbr/` w folder `LabCore_COA/` z jednym `.exe`. Laborant kopiuje folder na komputer, klika exe, działa. Jedyna zewnętrzna zależność: LibreOffice (zainstalowany osobno).

## Struktura wynikowa

```
LabCore_COA/
├── LabCore_COA.exe          # Entry point (noconsole)
├── _internal/               # PyInstaller runtime (Python, deps, templates, static)
├── data/                    # Writable — tworzona przy pierwszym uruchomieniu
│   ├── batch_db.sqlite
│   └── settings.json
└── labcore.ico
```

`data/` jest obok exe (portable) — dane podróżują z aplikacją.

## Zmiany

### 1. Nowy plik: `coa_app/launcher.py`

Entry point dla PyInstaller. Odpowiedzialności:

- Rozwiązuje ścieżki: `sys._MEIPASS` (frozen) vs `__file__` (dev)
- Ustawia `EXE_DIR` — katalog w którym leży .exe (parent of `_internal/`)
- Ustawia `DATA_DIR = EXE_DIR / "data"`, tworzy jeśli nie istnieje
- Eksportuje ścieżki jako env vars przed importem app.py
- Startuje Flask server na localhost:5050
- Otwiera przeglądarkę w trybie app (Chrome → Edge → domyślna)
- Zastępuje logikę z `start_coa.bat` w Pythonie

### 2. Zmiany w `coa_app/app.py`

Minimalne zmiany w sekcji konfiguracji ścieżek:

- `APP_DIR` — w frozen mode: `sys._MEIPASS`, w dev: `Path(__file__).parent`
- `DATA_DIR` — w frozen mode: z env var `LABCORE_DATA_DIR` (ustawiony przez launcher), w dev: `APP_DIR / "data"`
- `DB_PATH` — `DATA_DIR / "batch_db.sqlite"` (bez zmian w logice)
- `MBR_DIR` — w frozen mode: `sys._MEIPASS / "mbr"`, w dev: bez zmian

Reszta app.py bez zmian.

### 3. Nowy plik: `coa_app/labcore_coa.spec`

PyInstaller spec file:

```python
# Kluczowe ustawienia:
a = Analysis(
    ['launcher.py'],
    datas=[
        ('../mbr/templates', 'mbr/templates'),
        ('../mbr/static', 'mbr/static'),
        ('../mbr/cert_config.json', 'mbr'),
        ('../mbr/data/wzory', 'mbr/data/wzory'),  # DOCX templates
    ],
    hiddenimports=[
        'mbr', 'mbr.app', 'mbr.db', 'mbr.models',
        'mbr.auth', 'mbr.auth.routes',
        'mbr.certs', 'mbr.certs.routes', 'mbr.certs.generator', 'mbr.certs.models',
        'mbr.workers', 'mbr.workers.routes', 'mbr.workers.models',
        'mbr.registry', 'mbr.registry.routes', 'mbr.registry.models',
        'mbr.etapy', 'mbr.etapy.routes', 'mbr.etapy.models', 'mbr.etapy.config',
        'mbr.parametry', 'mbr.parametry.routes',
        'mbr.technolog', 'mbr.technolog.routes',
        'mbr.laborant', 'mbr.laborant.routes', 'mbr.laborant.models',
        'mbr.admin', 'mbr.admin.routes',
        'mbr.shared', 'mbr.shared.filters', 'mbr.shared.context',
        'num2words', 'bcrypt', 'docxtpl',
    ],
)
exe = EXE(..., name='LabCore_COA', console=False, icon='labcore.ico')
coll = COLLECT(...)  # onedir
```

### 4. Nowy plik: `coa_app/build_windows.bat`

Build script:

```bat
pip install pyinstaller
cd /d "%~dp0"
pyinstaller labcore_coa.spec --noconfirm
mkdir dist\LabCore_COA\data 2>nul
echo Gotowe: dist\LabCore_COA\
```

### 5. Usunięcie starych skryptów

Usuwamy (zastąpione przez .exe):
- `coa_app/SETUP.bat`
- `coa_app/INSTALL.bat`
- `coa_app/START.bat`
- `coa_app/install_windows.bat`
- `coa_app/start_coa.bat`

## Bez zmian

- Generowanie PDF — nadal LibreOffice (`soffice --headless`)
- `_find_soffice()` — szuka w PATH i Program Files
- Cały `mbr/` package — zero zmian w kodzie
- Logika sync z serwerem — bez zmian
- Frontend (HTML/CSS/JS) — bez zmian
- Port 5050, localhost only

## Zależności w bundlu

- flask, docxtpl, requests, bcrypt, urllib3, num2words
- NIE: gunicorn (serwer produkcyjny, niepotrzebny w desktop)

## Ryzyka

- **Antywirus**: Windows Defender może flagować unsigned .exe (rozwiązanie: whitelist lub code signing)
- **Rozmiar**: ~50-80MB (Python runtime + deps)
- **Hidden imports**: mogą być potrzebne dodatkowe — iteracyjnie przy buildzie
- **mbr `__init__.py`**: upewnić się że wszystkie podpakiety mają `__init__.py` (PyInstaller tego wymaga)