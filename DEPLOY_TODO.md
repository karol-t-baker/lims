# Deploy TODO — 2026-04-16

## Po deployu uruchom:

```bash
python -m scripts.migrate_standaryzacja_gate
```

Migracja warunków gate standaryzacji z `between 0..9999` (zawsze pass) na `w_limicie` (sprawdza limity produktowe). Bez tego panel korekcyjny standaryzacji nie dziala poprawnie — pokazuje sie zawsze zamiast tylko gdy parametry poza norma.

## Zmiany w DB (reczne, jednorazowe):

Substancja siarczynu w `etap_korekty_katalog` — jesli na produkcji jest `Siarczynian sodu`, zmien na `Siarczyn sodu`:

```sql
UPDATE etap_korekty_katalog SET substancja = 'Siarczyn sodu' WHERE substancja = 'Siarczynian sodu';
```

Bez tego korekta siarczynu przy sulfonowaniu nie zapisuje sie do DB (JS wysyla `Siarczyn sodu`, lookup failuje).

## Nowe parametry analityczne:

```bash
python -m scripts.add_ph1_barwa_gardner
```

Dodaje `ph_1proc` (pH roztworu 1%) i `barwa_gardner` (Barwa wg Gardnera) do `parametry_analityczne`.
