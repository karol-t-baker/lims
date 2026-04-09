# Cert Watchdog — Design Spec

## Cel

Skrypt PowerShell monitorujący folder Downloads na stacji Windows. Rozpoznaje pobrane świadectwa PDF po nazwie produktu i przenosi je do uporządkowanej struktury katalogów. Archiwizuje nadpisywane pliki.

## Komponenty

### 1. `cert-watchdog.ps1` — główny skrypt

- Czyta konfigurację z `cert-watchdog.json` (ten sam folder co skrypt)
- Rejestruje .NET `FileSystemWatcher` na folder źródłowy, filtr `*.pdf`
- Przy zdarzeniu `Created`: parsuje nazwę pliku, sprawdza czy pasuje do znanego produktu
- Jeśli pasuje — tworzy strukturę katalogów i przenosi plik
- Jeśli nie pasuje — ignoruje (zostawia w Downloads)
- Działa w tle bez okna, uruchamiany jako Scheduled Task przy logowaniu

### 2. `cert-watchdog.json` — konfiguracja

```json
{
  "watch_dir": "C:\\Users\\lab\\Downloads",
  "dest_dir": "C:\\Swiadectwa"
}
```

Ścieżki konfigurowalne. Skrypt szuka pliku JSON w swoim katalogu.

## Parsowanie nazwy pliku

### Format nazwy (z `_cert_names()` w `mbr/certs/generator.py`)

```
{product_folder} {variant_suffix} {nr_partii}.pdf
```

Przykłady:
- `Chegina K40GLOL 4.pdf` (base variant, bez suffixu)
- `Chegina K40GLOL Loreal MB 4.pdf` (z suffixem wariantu)
- `Chegina K7 12.pdf`
- `Cheminox K 3.pdf`

### Algorytm rozpoznawania

1. Lista znanych produktów hardcoded w skrypcie (z `PRODUCTS` w `laborant/models.py`), z `_` zamienione na spacje
2. Sortowana longest-first (żeby `Chegina K40GLOL` matchował przed `Chegina K40GL`)
3. Sprawdza czy nazwa PDF zaczyna się od nazwy produktu
4. Jeśli tak — to jest świadectwo, produkt = matched prefix
5. Jeśli nie pasuje żaden produkt — plik ignorowany

### Struktura docelowa

```
{dest_dir}\{rok}\{product_folder}\{oryginalny_pdf_name}
```

Gdzie:
- `rok` = bieżący rok (np. `2026`)
- `product_folder` = zmatchowany produkt (np. `Chegina K40GLOL`)
- `oryginalny_pdf_name` = pełna oryginalna nazwa pliku

Przykład: `C:\Swiadectwa\2026\Chegina K40GLOL\Chegina K40GLOL Loreal MB 4.pdf`

## Ochrona przed nadpisaniem

Jeśli plik docelowy już istnieje (np. regeneracja świadectwa):

1. Stary plik przenoszony do podfolderu `_archiwum\` w tym samym katalogu
2. Nowy plik zajmuje miejsce starego

```
Przed:
  2026\Chegina K40GLOL\Chegina K40GLOL 4.pdf        ← stary

Po:
  2026\Chegina K40GLOL\_archiwum\Chegina K40GLOL 4.pdf  ← stary (przeniesiony)
  2026\Chegina K40GLOL\Chegina K40GLOL 4.pdf             ← nowy
```

Jeśli w `_archiwum` też istnieje plik o tej nazwie, dodawany jest timestamp: `Chegina K40GLOL 4 (2026-04-08 15-03).pdf`.

## Deploy

- Plik `cert-watchdog.ps1` + `cert-watchdog.json` na stacji Windows
- Scheduled Task: uruchomienie przy logowaniu, bez okna, trigger: `At log on`
- Komenda: `powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\path\cert-watchdog.ps1"`

## Tech Stack

- PowerShell 5.1+ (wbudowany w Windows)
- .NET `System.IO.FileSystemWatcher`
- Zero zewnętrznych zależności
