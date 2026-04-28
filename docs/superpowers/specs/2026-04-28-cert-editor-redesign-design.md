# Cert Editor Redesign — Design Spec

**Data:** 2026-04-28
**Autor:** Tabaka Karol + Claude (brainstorming session)
**Scope:** `/admin/wzory-cert` — edytor szablonów świadectw jakości (admin)

## Problem

Obecny edytor (`mbr/templates/admin/wzory_cert.html`) ma trzy bolączki:

1. **Czytelność** — tabela parametrów w jednym wierszu próbuje zmieścić: drag-handle, Nazwa PL, Nazwa EN, Wymaganie, Metoda, Powiąż z pomiarem, Precyzja, Wynik opisowy, Delete. Długie pola (Wymaganie, Metoda — np. „PN-EN ISO 5661:2002 +Ap1:2016") są wizualnie ucinane, choć dane w polach są kompletne.

2. **Brak globalnego rejestru w UX** — dane globalne istnieją w `parametry_analityczne` (`label`, `name_en`, `method_code`), a edytor je „kradnie" przy wyborze kodu i zapisuje skopiowane wartości jako per-produkt nadpisanie w `parametry_cert.name_pl/name_en/method`. Efekt: zmiana w rejestrze nie propaguje się — admin musi ręcznie poprawiać każdy produkt.

3. **Surowy markup** — nazwy parametrów używają `_{D}` `^{20}` zamiast prawdziwych indeksów. Live preview działa pod inputem, ale samo wpisywanie wymaga znajomości składni LaTeX-podobnej. Niedostępne dla nietechnicznego usera.

## Decyzje projektowe

### 1. Semantyka: rejestr jest prawdą kanoniczną

`parametry_analityczne.label / name_en / method_code` to wartości globalne — to one są źródłem prawdy. `parametry_cert.name_pl / name_en / method` istnieją wyłącznie jako jawne nadpisania per produkt. **Pusta wartość (NULL) w `parametry_cert` = dziedziczenie z rejestru.**

Cert generator (`mbr/certs/generator.py` + `mbr/parametry/registry.py:get_cert_params`) już ma fallback: `r["cert_name_pl"] or r["label"]`. Backend renderingu nie wymaga zmian.

### 2. Layout: master-detail (lewy panel listy, prawy panel edycji)

Zakładka „Parametry świadectwa" w edytorze przechodzi na układ 280px : reszta:

**Lewy panel** — lista parametrów:
- Każda pozycja: drag-handle, **renderowana nazwa** parametru (sub/sup wyświetlone wizualnie, nie surowy `_{}^{}`), tag z kodem (np. `nD20`)
- „+ Dodaj parametr" na dole
- Aktywny parametr podświetlony (lewy border teal)

**Prawy panel** — edytor jednego parametru w siatce dwóch kolumn:

| Lewa kolumna (globalne — rejestr) | Prawa kolumna (per produkt — puste = dziedzicz) |
|---|---|
| Nazwa PL | Nazwa PL (override) |
| Nazwa EN | Nazwa EN (override) |
| Metoda | Metoda (override) |

Pola jedno-kolumnowe (zawsze per produkt, nie ma sensu globalnie):
- Wymaganie
- Precyzja
- Wynik opisowy (qualitative_result)
- Powiąż z pomiarem (parametr_id binding)

**Banner** nad lewą kolumną: `⚠ Edytujesz wartości w rejestrze — dotknięte produkty: N` (live count z nowego endpointu `/api/parametry/<id>/usage-impact`). Banner pojawia się tylko gdy admin zmodyfikował co najmniej jedno pole w lewej kolumnie.

### 3. Toolbar formatowania nad polami nazwy

Nad każdym inputem nazwy (PL i EN, w obu kolumnach):

```
[X²]  [X₂]  [↲]  |  [≤]  [≥]  [÷]  [°]
```

Klik wstawia odpowiedni token w pozycji kursora:
- `[X²]` → `^{}` (kursor w środku)
- `[X₂]` → `_{}`
- `[↲]` → `|` (manual line break — `mbr/certs/generator.py` już to obsługuje przez `<w:r><w:br/></w:r>`)
- `[≤] [≥] [÷] [°]` → bezpośrednio znak Unicode

Toolbar zawsze widoczny (nie on-focus) — pokazuje od razu możliwości adminowi nietechnicznemu.

Live preview pod każdym polem nazwy (już jest w kodzie, `updateRtPreview`) — bez zmian, renderuje wstawione tokeny.

### 4. Zapisywanie

Jeden przycisk `Zapisz wszystko` na dole edytora (jak teraz). Backend (`/api/cert/config/product/<key>` PUT) obsługuje obie kategorie zmian w jednej transakcji:

- Zmiany w lewej kolumnie (globalne) → `UPDATE parametry_analityczne SET label/name_en/method_code = ?` (audytowane jako `parametry.registry.updated`)
- Zmiany w prawej kolumnie (per-produkt) → `UPDATE parametry_cert SET name_pl/name_en/method = ?` (NULL gdzie puste)

Frontend wysyła pełen stan obu kolumn; backend porównuje z aktualnym DB i emituje zmiany. Status flash: `Zapisano: 3 globalne, 2 per produkt` — explicytna liczba dla każdego rodzaju.

### 5. Warianty

Zakładka „Warianty" dostaje ten sam dwukolumnowy układ, ale **lewa kolumna pokazuje wartość efektywną bazy** (globalne `parametry_analityczne` + produktowe nadpisania `parametry_cert variant_id IS NULL`) jako tylko-do-odczytu. Prawa kolumna = nadpisanie wariantu (`parametry_cert variant_id = X`).

Tag w lewej kolumnie pokazuje skąd pochodzi efektywna wartość:
- `[rejestr]` — wartość z `parametry_analityczne`
- `[produkt]` — wartość z `parametry_cert variant_id IS NULL`

Klik „edytuj globalnie" lub „edytuj produktowo" w wariancie redirektuje na zakładkę „Parametry świadectwa" produktu bazowego dla danego parametru.

### 6. Migracja istniejących nadpisań

Jednorazowy skrypt `scripts/migrate_cert_override_cleanup.py` (uruchamiany ręcznie, idempotentny):

- Iteruje przez wszystkie wiersze `parametry_cert`
- Dla każdego pola (`name_pl`, `name_en`, `method`):
  - JOIN z `parametry_analityczne` po `parametr_id`
  - Jeśli wartość override == wartość globalna (`label / name_en / method_code`) → `SET NULL`
- Loguje:
  - liczbę wierszy zaktualizowanych (per pole)
  - liczbę nadpisań pozostałych jako jawne (per produkt, per pole)
  - listę produktów z największą liczbą jawnych nadpisań (top 10) — do audytu

Po uruchomieniu skryptu: ~80–90% pól będzie pustych i wyświetli się w UI jako dziedziczone z rejestru. Pozostałe to faktyczne nadpisania per produkt — admin widzi je jasno.

Skrypt nie modyfikuje `parametry_analityczne`. Skrypt nie zmienia logiki rendering — cert generator już zwraca poprawną wartość (fallback `cert_name_pl or label`).

### 7. Nowe endpointy backend

- `PUT /api/parametry/<id>/registry` — admin edytuje `label`, `name_en`, `method_code` w `parametry_analityczne`. Audytowane jako `parametry.registry.updated`. Wymaga roli `admin`.
- `GET /api/parametry/<id>/usage-impact` — zwraca:
  ```json
  {
    "products_total": 8,
    "products_with_overrides": {
      "name_pl": 0,
      "name_en": 1,
      "method": 2
    }
  }
  ```
  Frontend używa tego do bannera „dotknięte produkty: 8".
- Modyfikacja `mbr/parametry/registry.py:get_cert_params` i `get_cert_variant_params` — zwracają teraz **dwa zestawy pól**:
  - `name_pl_global / name_en_global / method_global` — z `parametry_analityczne` (zawsze obecne, nie NULL)
  - `name_pl_override / name_en_override / method_override` — z `parametry_cert`, raw (mogą być NULL)
  - Pole `name_pl / name_en / method` (efektywna wartość, fallback) zostaje zachowane dla kompatybilności z istniejącym cert generatorem
  Stary endpoint `/api/cert/config/product/<key>` zwraca te pola obok dotychczasowych — frontend renderuje obie kolumny, backend renderingu używa tylko efektywnej wartości.

### 8. Dodawanie nowego parametru do świadectwa

Klik „+ Dodaj parametr" w lewym panelu listy:
1. Modal z `<select>` listą kodów z `_availableCodes` (jak teraz, z grupowaniem „W MBR" / „Poza MBR")
2. Po wyborze kodu — nowy wiersz w `parametry_cert` z `parametr_id = X`, wszystkie pola override = NULL
3. Edytor pokazuje od razu wartości z rejestru w lewej kolumnie (read-only z tagiem `[rejestr]`), prawa kolumna pusta (`puste = dziedzicz`)
4. Admin może od razu edytować wymaganie/precyzję/wynik opisowy (per produkt) lub kliknąć „Nadpisz" przy nazwie/metodzie żeby ustawić override

Dodanie zupełnie nowego parametru (nowy `kod` w rejestrze) nie odbywa się w edytorze cert — to flow w `/admin/parametry`.

### 9. Poza scope (zostaje bez zmian)

- Modal „Ustawienia globalne świadectw" (font, title/product/body sizes — `cert_settings` table)
- Panel aliasów cert (`/admin/wzory-cert` sekcja „Aliasy cert")
- Cert generator backend (`mbr/certs/generator.py`) — fallback semantyka już prawidłowa
- Lista produktów + zakładki Produkt / Historia / Podgląd PDF
- Tabela `cert_settings` i jej UI
- Per-produkt opcje wariantów (flagi, av-on, opinions overrides)

## Architektura — ścieżka rozwoju

### PR1 — Backend
- Endpoint `PUT /api/parametry/<id>/registry`
- Endpoint `GET /api/parametry/<id>/usage-impact`
- Modyfikacja `get_cert_params` / `get_cert_variant_params` (dwa zestawy pól)
- Audyt `parametry.registry.updated` w `mbr/admin/audit.py`
- Testy:
  - `tests/test_parametry_registry_edit.py` — PUT registry zmienia globalne wartości, audytowane
  - `tests/test_cert_params_dual_field.py` — get_cert_params zwraca global + override osobno
  - `tests/test_usage_impact.py` — count produktów + nadpisań

### PR2 — Frontend (Parametry)
- Master-detail layout w zakładce „Parametry świadectwa" (`mbr/templates/admin/wzory_cert.html`)
- Dwukolumnowy edytor (lewa: globalne, prawa: per produkt)
- Toolbar formatowania (X² X₂ ↲ ≤ ≥ ÷ °) nad polami nazwy
- Banner usage-impact gdy lewa kolumna zmieniona
- `Save` rozdziela zmiany do dwóch endpointów (registry + cert config)
- Live preview z istniejącym `_rtHtml` / `updateRtPreview`

### PR3 — Frontend (Warianty)
- Ten sam układ master-detail w zakładce „Warianty"
- Lewa kolumna = wartość efektywna bazy (read-only z tagiem `[rejestr]` lub `[produkt]`)
- Prawa kolumna = nadpisanie wariantu
- Link „edytuj globalnie/produktowo" przekierowuje do bazowego edytora

### PR4 — Migracja produkcyjna
- Skrypt `scripts/migrate_cert_override_cleanup.py`
- Smoke test na kopii bazy
- Uruchomienie na produkcji + log do audytu
- Krótka dokumentacja w `docs/migrations/2026-04-cert-override-cleanup.md`

## Akceptacja

- [ ] Edycja `label` w rejestrze (np. zmiana „Współczynnik załamania" na inną nazwę) propaguje się do wszystkich świadectw używających tego parametru bez ręcznej edycji każdego produktu
- [ ] Wymaganie i Metoda nigdy nie są ucinane wizualnie w edytorze
- [ ] Nazwy parametrów wyświetlają się z renderowanymi indeksami (n<sub>D</sub><sup>20</sup>) w liście parametrów po lewej i w nagłówku panelu edycji
- [ ] Przyciski sub/sup wstawiają tokeny `_{}` `^{}` w pozycji kursora bez konieczności pisania ich ręcznie
- [ ] Banner usage-impact pokazuje poprawną liczbę produktów po edycji wartości globalnej
- [ ] Po migracji `parametry_cert` ma głównie NULL-e w name_pl/name_en/method (z wyjątkiem faktycznych jawnych nadpisań); cert generator generuje identyczne PDFy jak przed migracją
- [ ] Warianty pokazują efektywną wartość bazy w lewej kolumnie i nadpisanie wariantu w prawej
- [ ] Audyt rejestruje każdą edycję rejestru jako `parametry.registry.updated`
