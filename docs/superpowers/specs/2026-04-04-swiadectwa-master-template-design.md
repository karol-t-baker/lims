# Design: System generowania świadectw z jednego master template

Data: 2026-04-04
Status: Zatwierdzony

---

## Problem

86 plików .docx z wzorami świadectw jakości. Obecny system parsuje .docx i wypełnia wartości. Trudne do utrzymania, modyfikacji i rozbudowy. Brak jednego źródła prawdy.

## Rozwiązanie

Jeden master HTML template + JSON config per produkt/wariant → PDF przez weasyprint.

---

## Architektura

```
cert_config.json          ← konfiguracja produktów, parametrów, wariantów
       ↓
cert_gen_v2.py            ← silnik generowania (zastępuje cert_gen.py + cert_mappings.py)
       ↓
cert_master.html          ← Jinja2 master template (1 plik)
cert_master.css           ← style layoutu świadectwa
       ↓
weasyprint                ← render HTML → PDF
       ↓
data/swiadectwa/*.pdf     ← wynikowe PDFy
```

### Flow generowania

```
1. Laborant klika "Generuj świadectwo" na ukończonej analizie zbiornika
2. System wyświetla listę dostępnych wariantów (jak teraz)
3. Laborant wybiera wariant (np. "Chegina K7 — ADAM&PARTNER MB")
4. System sprawdza czy wariant wymaga dodatkowych pól:
   - has_order_number → popup: "Numer zamówienia / Order No."
   - has_certificate_number → popup: "Numer certyfikatu / Certificate No."
   - has_avon_fields → popup: "Kod AVON", "Nazwa AVON"
5. System pobiera dane z ebr_wyniki (analiza zbiornika)
6. cert_gen_v2.py:
   a. Ładuje config produktu + wariantu z cert_config.json
   b. Łączy: stałe pola (spec, CAS, pola jakościowe) + wyniki analizy + pola z popupu
   c. Renderuje cert_master.html przez Jinja2
   d. Konwertuje HTML → PDF przez weasyprint
7. Zapisuje PDF + rekord w tabeli swiadectwa
```

---

## Struktury danych

### cert_config.json — struktura

```json
{
  "company": {
    "name": "PPU Chemco Spółka z o.o.",
    "address": "ul. Kościuszki 19, 83-033 Sobowidz",
    "email": "biuro@chemco.pl",
    "bdo": "000003546"
  },
  "footer": {
    "country_pl": "Polska",
    "country_en": "Poland",
    "issuer_pl": "Specjalista ds. KJ",
    "issuer_en": "Quality Control Specialist",
    "electronic_clause_pl": "Dokument utworzony elektronicznie, nie wymaga podpisu.",
    "electronic_clause_en": "The certificate is not signed as it is electronically edited."
  },
  "products": {
    "Chegina_K40GLOL": {
      "display_name": "Chegina K40GLOL",
      "spec_number": "P833",
      "cas_number": "147170-44-3",
      "expiry_months": 12,
      "opinion_pl": "Produkt odpowiada wymaganiom P833",
      "opinion_en": "The product complies with P833",
      "qualitative_fields": {
        "odour_pl": "słaby",
        "odour_en": "faint",
        "appearance_pl": "klarowna ciecz",
        "appearance_en": "clear liquid"
      },
      "parameters": [
        {
          "id": "barwa_hz",
          "name_pl": "Barwa w skali Hazena",
          "name_en": "Colour (Hazen scale)",
          "requirement": "max 150",
          "method": "L928",
          "data_field": "barwa_hz",
          "format": "{value:.0f}"
        },
        {
          "id": "odour",
          "name_pl": "Zapach",
          "name_en": "Odour",
          "requirement": "słaby /faint",
          "method": "organoleptycznie /organoleptic",
          "data_field": null,
          "qualitative": true,
          "result_pl": "zgodny",
          "result_en": "right"
        },
        {
          "id": "appearance",
          "name_pl": "Wygląd",
          "name_en": "Appearance",
          "requirement": "klarowna ciecz /clear liquid",
          "method": "organoleptycznie /organoleptic",
          "data_field": null,
          "qualitative": true,
          "result_pl": "zgodny",
          "result_en": "right"
        },
        {
          "id": "ph",
          "name_pl": "pH (20°C)",
          "name_en": "pH (20°C)",
          "requirement": "4,50-5,50",
          "method": "L905",
          "data_field": "ph_10proc",
          "format": "{value:.2f}"
        },
        {
          "id": "active_matter",
          "name_pl": "Substancja aktywna [%]",
          "name_en": "Active matter [%]",
          "requirement": "37,0-42,0",
          "method": "L932",
          "data_field": "sa",
          "format": "{value:.1f}"
        },
        {
          "id": "nacl",
          "name_pl": "NaCl [%]",
          "name_en": "NaCl [%]",
          "requirement": "5,8–7,3",
          "method": "L941",
          "data_field": "nacl",
          "format": "{value:.1f}"
        },
        {
          "id": "dry_matter",
          "name_pl": "Sucha masa [%]",
          "name_en": "Dry matter [%]",
          "requirement": "min. 44,0",
          "method": "L903",
          "data_field": "sm",
          "format": "{value:.1f}"
        },
        {
          "id": "h2o",
          "name_pl": "H2O [%]",
          "name_en": "H2O [%]",
          "requirement": "52,0 – 56,0",
          "method": "L903",
          "data_field": "h2o",
          "format": "{value:.1f}"
        },
        {
          "id": "free_amine",
          "name_pl": "Wolna kokamidopropylodimetyloamina [%]",
          "name_en": "Free cocamidopropyldimethylamine [%]",
          "requirement": "max 0,30",
          "method": "L904",
          "data_field": "wolna_amina",
          "format": "{value:.2f}"
        }
      ],
      "variants": [
        {
          "id": "base",
          "label": "Chegina K40GLOL",
          "flags": []
        },
        {
          "id": "loreal",
          "label": "Chegina K40GLOL — Loreal MB",
          "flags": ["has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "loreal_belgia",
          "label": "Chegina K40GLOL — Loreal Belgia MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "loreal_wlochy",
          "label": "Chegina K40GLOL — Loreal Włochy MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        },
        {
          "id": "kosmepol",
          "label": "Chegina K40GLOL — Kosmepol MB",
          "flags": ["has_order_number", "has_certificate_number", "has_rspo"],
          "overrides": {
            "spec_number": "P826",
            "opinion_pl": "Produkt odpowiada wymaganiom P826",
            "opinion_en": "The product complies with P826"
          }
        }
      ]
    }
  }
}
```

### Flagi wariantów

| Flaga | Pole w popupie | Opis |
|-------|----------------|------|
| `has_order_number` | Numer zamówienia / Order No. | Pole tekstowe, wymagane |
| `has_certificate_number` | Numer certyfikatu / Certificate No. | Pole tekstowe, wymagane |
| `has_rspo` | — | Wyświetla "CU-RSPO SCC-857488" na świadectwie (stały tekst) |
| `has_avon_code` | Kod AVON | Pole tekstowe, wymagane |
| `has_avon_name` | Nazwa AVON (INCI) | Pole tekstowe, wymagane |

### Parametr — typy

| Typ | `data_field` | `qualitative` | Opis |
|-----|-------------|---------------|------|
| Liczbowy | `"sm"`, `"nacl"`, etc. | false/brak | Wartość z ebr_wyniki, formatowana wg `format` |
| Jakościowy | null | true | Stały wynik: `result_pl` / `result_en` ("zgodny" / "right") |

---

## Pliki do stworzenia / zmodyfikowania

### Nowe pliki

| Plik | Opis |
|------|------|
| `mbr/cert_config.json` | Konfiguracja wszystkich produktów (31), wariantów (~86), parametrów |
| `mbr/templates/cert_master.html` | Jinja2 master template HTML — layout świadectwa |
| `mbr/static/cert_master.css` | Style CSS dopasowane do layoutu oryginalnych .docx |
| `mbr/cert_gen_v2.py` | Nowy silnik generowania: load_config() → build_context() → render_html() → render_pdf() |

### Modyfikowane pliki

| Plik | Zmiana |
|------|--------|
| `mbr/app.py` | Zmiana endpointu `/api/cert/generate` — wywołuje cert_gen_v2 zamiast cert_gen |
| `mbr/app.py` | Zmiana endpointu `/api/cert/templates` — listuje warianty z cert_config.json zamiast plików .docx |
| `mbr/templates/laborant/_fast_entry_content.html` | Popup z wymaganymi polami (nr zamówienia, nr certyfikatu, AVON) przed generowaniem |
| `mbr/seed_mbr.py` | Dodanie brakujących parametrów (barwa_hz, wolna_amina, etc.) |

### Pliki do zachowania (backward compat)

| Plik | Status |
|------|--------|
| `mbr/cert_gen.py` | Zachowany — stary system jako fallback |
| `mbr/cert_mappings.py` | Zachowany — reference, nie używany przez nowy system |
| `data/wzory/*.docx` | Zachowane — reference |

---

## Master template HTML — struktura

```html
{# cert_master.html #}
<div class="certificate">
  {# Nagłówek firmy #}
  <header class="company-header">
    <div class="logo"><!-- logo Chemco --></div>
    <div class="company-info">
      {{ company.name }}<br>
      {{ company.address }}<br>
      {{ company.email }} | BDO: {{ company.bdo }}
    </div>
  </header>

  {# Tytuł #}
  <h1>ŚWIADECTWO JAKOŚCI<br>/CERTIFICATE OF ANALYSIS</h1>
  <h2>{{ product.display_name }}</h2>

  {# Pola AVON (opcjonalne) #}
  {% if avon_code %}
  <p>AVON code: {{ avon_code }}</p>
  <p>AVON name: {{ avon_name }}</p>
  {% endif %}

  {# Dane identyfikacyjne #}
  <div class="batch-info">
    <p>Klasyfikowany na podstawie specyfikacji / Classified on TDS: {{ spec_number }}
       {% if cas_number %}CAS: {{ cas_number }}{% endif %}</p>
    <p>Partia / Batch: {{ nr_partii }}</p>
    <p>Data produkcji / Production date: {{ production_date }}</p>
    <p>Data ważności / Expiry date: {{ expiry_date }}</p>
    {% if order_number %}
    <p>Numer zamówienia / Order No.: {{ order_number }}</p>
    {% endif %}
    {% if certificate_number %}
    <p>Numer certyfikatu / Certificate No.: {{ certificate_number }}
       {% if has_rspo %}CU-RSPO SCC-857488{% endif %}</p>
    {% endif %}
  </div>

  {# Tabela parametrów #}
  <table class="params-table">
    <thead>
      <tr>
        <th>Parametr oznaczany<br>/Inspection characteristic</th>
        <th>Wymagania<br>/Requirement</th>
        <th>Metoda badań<br>/Test method</th>
        <th>Wynik<br>/Result</th>
      </tr>
    </thead>
    <tbody>
      {% for param in parameters %}
      <tr>
        <td>{{ param.name_pl }}<br>/{{ param.name_en }}</td>
        <td>{{ param.requirement }}</td>
        <td>{{ param.method }}</td>
        <td>{{ param.result }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  {# Stopka #}
  <div class="footer">
    <p><strong>Kraj pochodzenia / Country of origin:</strong> Polska/Poland</p>
    <p><strong>Opinia Laboratorium KJ / Opinion of Quality Control Laboratory:</strong></p>
    <p>{{ opinion_pl }}<br>/{{ opinion_en }}</p>
    <p>Sobowidz, {{ issue_date }}</p>
    <p><strong>Wystawił / The certificate made by:</strong></p>
    <p>Specjalista ds. KJ / Quality Control Specialist</p>
    <p><strong>{{ footer.electronic_clause_pl }}</strong><br>
    /{{ footer.electronic_clause_en }}</p>
  </div>
</div>
```

---

## cert_gen_v2.py — API

```python
def load_config() -> dict:
    """Ładuje cert_config.json"""

def get_variants(produkt: str) -> list[dict]:
    """Zwraca listę wariantów dla produktu (do wyświetlenia w UI)"""

def get_required_fields(produkt: str, variant_id: str) -> list[str]:
    """Zwraca listę flag wymagających inputu (has_order_number, etc.)"""

def generate_certificate(
    ebr_id: int,
    produkt: str,
    variant_id: str,
    extra_fields: dict  # {order_number, certificate_number, avon_code, avon_name}
) -> str:
    """
    Generuje PDF świadectwa.
    1. Pobiera wyniki z ebr_wyniki dla ebr_id
    2. Ładuje config produktu + wariantu
    3. Buduje kontekst (merge: config stałe + wyniki + extra_fields)
    4. Renderuje HTML przez Jinja2
    5. Konwertuje HTML→PDF przez weasyprint
    6. Zapisuje PDF do data/swiadectwa/
    7. Tworzy rekord w tabeli swiadectwa
    Returns: ścieżka do PDF
    """

def build_context(product_config: dict, variant: dict,
                   wyniki: dict, extra_fields: dict) -> dict:
    """
    Buduje kontekst Jinja2:
    - Dla parametrów liczbowych: pobiera wartość z wyniki[data_field], formatuje
    - Dla parametrów jakościowych: wstawia stały result_pl/result_en
    - Stosuje variant overrides (spec_number, dodatkowe/usunięte parametry)
    - Oblicza daty (produkcji, ważności)
    - Formatuje wartości liczbowe z przecinkiem (polski format)
    """
```

---

## Uzupełnienie luk w seed_mbr.py

### Priorytet 1: barwa_hz (22 produkty)

Dodać `barwa_hz` (Barwa Hazen, bezpośredni, 0-500) do:
- Chegina_K40GLOL, K40GLOL_HQ, K40GLOS, K7GLO, K7B, KK, CC, CCR
- Cheminox_K, Cheminox_K35, Cheminox_LA
- Monamid_S, Monamid_L
- i inne z listy w gap analysis

### Priorytet 2: wolna_amina (5 produktów)

Dodać `wolna_amina` (wolna amina, bezpośredni, 0-1.0%) do:
- Chegina_KK, K40GL, K40GLN, K40GLOS, GLOL40

### Priorytet 3: brakujące per produkt

| Produkt | Brakujący parametr | Typ |
|---------|-------------------|-----|
| Chegina_K40GLO | gestosc (gęstość) | bezpośredni |
| Chegina (generic) | nd20 | bezpośredni |
| Chelamid_DK | dea | bezpośredni |

---

## Styl CSS — cel: pixel-perfect z oryginałem

- Format A4, marginesy ~2cm
- Font: Times New Roman / Liberation Serif (jak w .docx)
- Logo Chemco w lewym górnym rogu
- Tabela parametrów: obramowanie 1px solid black, padding 4px
- Nagłówki kolumn: bold, wyśrodkowane
- Bilingual: polski / english w osobnych liniach (lub /separated)
- Stopka: na dole strony

---

## Etap 2 (przyszłość) — edytor split-screen

Nie w zakresie etapu 1. Założenia na przyszłość:
- Lewy panel: formularz edycji cert_config.json (dodaj/usuń parametry, zmień wymagania)
- Prawy panel: live preview PDF (re-render przy każdej zmianie)
- Kierownik może tworzyć nowe produkty i warianty z UI
- Zmiany zapisywane do cert_config.json (lub DB)
