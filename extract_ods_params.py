#!/usr/bin/env python3
"""Extract parameter data from ODS spreadsheets and update batch_db.sqlite."""

import re
import json
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/batch_db.sqlite")
PIONOWE = Path("docs/swiadectwa/tabelki - pionowe.ods")
POZIOME = Path("docs/swiadectwa/tabelki - poziome.ods")

# Columns to skip
SKIP_COLS = {
    'NUMER PARTII', 'DATA PRODUKCJI', 'PODPIS', 'UWAGI', 'ZBIORNIK',
    'Nastaw', 'NUMER DOPUSZCZENIA', 'NUMER ZAMÓWIENIA', 'C16', 'C18',
    'DATA WAŻNOŚCI', 'ILOŚĆ [t]', 'NUMERY PARTII ALKOHOLE 30/70 I EO20',
    'RODZAJ', 'Nr dop. Oleju kokos.', 'Konserwant', 'TEST STAB. EMULSJI (cieplarka 30oC)',
    'Lepkość',
}

# Sheets to skip entirely
SKIP_SHEETS = {'Katalizator_KOH_glikol_prop_', 'Arkusz1', 'Arkusz2', 'Arkusz3'}

# Sheet name -> DB product name mapping
SHEET_TO_PRODUCT = {
    'Alstermid_K': 'Alstermid_K',
    'Alstermid': 'Alstermid',
    'Chegina': 'Chegina',
    'Chegina_K40GLOL': 'Chegina_K40GLOL',
    'Chegina_KK': 'Chegina_KK',
    'Chegina_K': 'Chegina_K7',  # old sheet name
    'Chegina_K7': 'Chegina_K7',
    'Chegina_L9': 'Chegina_L9',
    'Chelamid_DK': 'Chelamid_DK',
    'HSH_CS_30_70': 'HSH_CS_3070',
    'Chemal_CS_30_70': 'Chemal_CS_3070',
    'Chemal_EO_20': 'Chemal_EO20',
    'Cheminox_K': 'Cheminox_K',
    'Cheminox_K_35': 'Cheminox_K35',
    'Cheminox_LA': 'Cheminox_LA',
    'Chemipol_ML': 'Chemipol_ML',
    'Chemipol_OL': 'Chemipol_OL',
    'Citrowax': 'Citrowax',
    'Dister_E': 'Dister_E',
    'Glikoster_P': 'Glikoster_P',
    'Kwas_stearynowy': 'Kwas_Stearynowy',
    'Monamid_K': 'Monamid_K',
    'Monamid_L': 'Monamid_L',
    'Monamid_S': 'Monamid_S',
    'Monester_O': 'Monester_O',
    'Monester_S': 'Monester_S',
    'Perlico_45': 'Perlico_45',
    'Polcet_A': 'Polcet_A',
    'Chemal_SE-12': 'Chemal_SE12',
    'Chemal_PC': 'Chemal_PC',
    'Chegina_KK1': 'Chegina_KK',  # duplicate of Chegina_KK
    'Sles': 'SLES',
    # Poziome sheets
    'Chegina_K40_GLOL': 'Chegina_K40GLOL',
    'chegina_k40_glos': 'Chegina_K40GLOS',
    'Chegina_K40_GLOL_HQ': 'Chegina_K40GLOL_HQ',
    'Chegina_K7GLO': 'Chegina_K7GLO',
    'Chegina_K40GL': 'Chegina_K40GL',
    'Chegina_K40_GLO': 'Chegina_K40GLO',
    'Chegina_CCR': 'Chegina_CCR',
    'Chegina_K7B': 'Chegina_K7B',
    'POLCET_A': 'Polcet_A',
    'Chegina_CC': 'Chegina_CC',
    'Chegina_K40GLOL': 'Chegina_K40GLOL',
    'Monamid_KO': 'Monamid_KO',
    'Monamid_KO_Revada': 'Monamid_KO_Revada',
    'Alkinol_Alkinol_B_': None,  # special: two products
}

def clean_text(s):
    """Clean whitespace from text."""
    if pd.isna(s):
        return ''
    return re.sub(r'\s+', ' ', str(s).strip())

def extract_spec_number(row0_values):
    """Extract spec number (P### or ZN-####) from header row."""
    for v in row0_values:
        if pd.isna(v):
            continue
        s = str(v).strip()
        # Find P### pattern
        m = re.search(r'(P\d{3,4})', s)
        if m:
            return m.group(1)
        # Find ZN-#### pattern
        m = re.search(r'(ZN-\d{4}/[^\s]+)', s)
        if m:
            return m.group(1)
    return None

def parse_requirement(col_text):
    """Extract parameter name and requirement from column header.

    Examples:
      'S. MASA (min. 35,5%)' -> ('S. MASA', 'min 35,5')
      'pH 10% (4,5 – 7,5)' -> ('pH 10%', '4,5-7,5')
      'BARWA (max 3)' -> ('BARWA', 'max 3')
    """
    col_text = clean_text(col_text)
    if not col_text:
        return None, None

    # Try to extract requirement in parentheses or brackets
    # Match content in () or []
    m = re.search(r'[\(\[]\s*(.+?)\s*[\)\]]', col_text)
    if m:
        req_raw = m.group(1)
        name_part = col_text[:m.start()].strip()
        # Clean up requirement
        req = req_raw.replace('–', '-').replace('—', '-').replace('  ', ' ').replace('%', '').strip()
        req = re.sub(r'\s*-\s*', '-', req)
        req = req.replace('max.', 'max').replace('min.', 'min').replace('max,', 'max')
        req = req.strip('. ')
        if not name_part:
            name_part = col_text
        return name_part, req

    # No parentheses - just return name, no requirement
    return col_text, None


def map_param_to_kod(name, requirement=None):
    """Map a parameter name from spreadsheet to parametry_analityczne.kod."""
    n = name.upper().strip().rstrip('.')

    # Skip columns
    for skip in SKIP_COLS:
        if skip.upper() in n:
            return None

    # Specific mappings
    if re.match(r'^S\.?\s*M(ASA|\.?\s*$|\.)', n) or n == 'SM' or n.startswith('SUCHA MASA') or '%S.M' in n or n.startswith('S.M') or n.startswith('% S.M') or n == 'SM' or 'S. MASA' in n:
        return 'sm'
    if 'NACL' in n or 'ZAW. NACL' in n:
        return 'nacl'
    if re.search(r'PH\s*(10|5|W\s|3)', n) or n.startswith('PH (10') or n.startswith('PH (5') or n.startswith('PH (3'):
        return 'ph_10proc'
    if n.startswith('PH') and '1%' in n:
        return 'ph'
    if n == 'PH' or n.startswith('PH ('):
        return 'ph_10proc'
    if 'BARWA' in n:
        if 'HAZEN' in n or 'HZ' in n:
            return 'barwa_hz'
        if 'JODOW' in n or 'GARDNER' in n or 'FAU' in n or '301' in n:
            return 'barwa_fau'
        if re.search(r'MAX\s*\d', n):
            # barwa with numeric max — check if large number (Hz) or small (Iodine)
            m = re.search(r'MAX\.?\s*(\d+)', n)
            if m:
                val = int(m.group(1))
                if val >= 50:
                    return 'barwa_hz'
                else:
                    return 'barwa_fau'
        # If requirement mentions Hz
        if requirement and 'HZ' in requirement.upper():
            return 'barwa_hz'
        # Default - check requirement value
        if requirement:
            m2 = re.search(r'(\d+)', requirement)
            if m2 and int(m2.group(1)) >= 50:
                return 'barwa_hz'
        return 'barwa_fau'
    if n.startswith('BARWA') and ('BEZBARWNA' in n or 'JASNOŻÓŁTA' in n):
        return 'barwa_opis'
    if re.search(r'%?\s*S\.?\s*A\.?', n) and 'MASA' not in n:
        return 'sa'
    if 'ND20' in n.replace(' ', '') or n.startswith('ND20') or n == 'ND20':
        return 'nd20'
    if n.startswith('ND60') or 'ND60' in n:
        return 'nd20'  # same instrument, different temp
    if re.search(r'L\.?\s*KWAS', n) or n == 'LK' or n.startswith('L. KWAS') or n.startswith('L.KWAS') or 'LICZBA KWASOWA' in n:
        return 'lk'
    if re.search(r'L\.?\s*ZMYDL', n) or n == 'LZ' or n.startswith('LICZBA ZMYDL'):
        return 'lz'
    if re.search(r'L\.?\s*HYDROK', n) or n == 'LOH' or n == 'L.OH' or n.startswith('LICZBA HYDROK'):
        return 'lh'
    if re.search(r'L\.?\s*JOD', n) or n == 'LI' or n.startswith('LICZBA JOD'):
        return 'li'
    if re.search(r'T\.?\s*KROPL', n) or n.startswith('TEMP. KROPL') or n.startswith('T. KROPL'):
        return 't_kropl'
    if 'KRZEPNIĘCIA' in n or 'T. KRZEPN' in n:
        return 't_krzep'
    if re.search(r'T\.?\s*TOPN', n):
        return 't_topn'
    if 'H2O2' in n or 'H202' in n or 'ZAW. H2O2' in n or 'NADTLEN' in n:
        return 'h2o2'
    if re.search(r'H2O(?!2)', n) or 'ZAW. WODY' in n or 'ZAWARTOŚĆ WODY' in n:
        return 'h2o'
    if '%WKT' in n or n == 'WKT' or n.startswith('% WKT'):
        return 'wkt'
    if '%MEA' in n or n == 'MEA' or n.startswith('% MEA'):
        return 'mea'
    if '% AA' in n or n.startswith('%AA') or n == 'AA' or n.startswith('% AA'):
        return 'aa'
    if 'ESTRY' in n and 'MONO' not in n:
        return 'estry'
    if 'DMAPA' in n:
        return 'dmapa'
    if 'MCA' in n:
        return 'mca'
    if 'DCA' in n:
        return 'dca'
    if 'SO3' in n or 'SIARCZYN' in n:
        return 'so3'
    if 'GĘSTOŚĆ' in n or 'GESTOSC' in n or n.startswith('GĘSTOŚĆ'):
        return 'gestosc'
    if 'WOLNA AMINA' in n or 'WOLNEJ AMINY' in n:
        return 'wolna_amina'
    if 'WOLNY GLIKOL' in n:
        return 'wolny_glikol'
    if 'MONOESTRY' in n or 'MONOESTR' in n:
        return 'monoestry'
    if 'MONOGLICE' in n or 'MONOGLICERYD' in n:
        return 'monoglicerydy'
    if 'WGE' in n:
        return 'wge'
    if 'DIETANOL' in n or n == 'DEA' or n.startswith('%DEA') or n.startswith('% DEA'):
        return 'dietanolamina'
    if 'KLAROWN' in n:
        return 'klarownosc'
    if 'TLENKU' in n and 'AMINY' in n:
        return 'tlenek_aminowy'
    if 'L. AMINOWA' in n or 'LICZBA AMINOWA' in n or n == 'LA':
        return 'la'
    if 'ALKALICZN' in n or 'ALKAICZN' in n:
        return 'alkalicznosc'
    if 'GLIKOLAN' in n:
        return None  # skip for now - not in parametry_analityczne
    if 'ZAW. METALI' in n or 'PB [PPM]' in n or 'AS [PPM]' in n or 'HG [PPM]' in n:
        return None  # heavy metals - skip
    if 'GLICERYN' in n or '% GLICERYNY' in n:
        return 'gliceryny'
    if n == 'ME' or n.startswith('DES') or n == 'L. KW':
        return None  # calculated fields, skip

    return None


def parse_sheet_pionowe(sheet_name, df):
    """Parse a vertical-layout sheet."""
    if sheet_name in SKIP_SHEETS:
        return None

    product_name = SHEET_TO_PRODUCT.get(sheet_name)
    if product_name is None and sheet_name not in SHEET_TO_PRODUCT:
        print(f"  WARNING: Unknown sheet {sheet_name!r}, skipping")
        return None
    if product_name is None:
        return None  # explicitly set to None (like Alkinol combined sheet)

    # Find the header row (row with parameter columns)
    # Usually row 0 has product name + spec, row 1 has columns
    row0 = df.iloc[0] if len(df) > 0 else pd.Series()

    # Find spec number from row 0
    spec = extract_spec_number(row0.values)

    # Find header row - the one containing 'NUMER PARTII'
    header_row_idx = None
    for i in range(min(5, len(df))):
        row_vals = [clean_text(v) for v in df.iloc[i]]
        if any('NUMER PARTII' in v for v in row_vals):
            header_row_idx = i
            break

    if header_row_idx is None:
        print(f"  WARNING: No header row found in {sheet_name}")
        return None

    header = df.iloc[header_row_idx]

    # Also check if there's a sub-header row (like Monamid_K with WKT split)
    sub_header = None
    if header_row_idx + 1 < len(df):
        sub_row = df.iloc[header_row_idx + 1]
        sub_vals = [clean_text(v) for v in sub_row]
        if any(v and 'NUMER PARTII' not in v for v in sub_vals):
            sub_header = sub_row

    params = []
    for col_idx in range(len(header)):
        col_text = clean_text(header.iloc[col_idx])
        if not col_text:
            continue

        # Check if this is a skip column
        skip = False
        for sc in SKIP_COLS:
            if sc.upper() in col_text.upper():
                skip = True
                break
        if skip:
            continue

        # Check sub-header for additional info
        if sub_header is not None:
            sub_text = clean_text(sub_header.iloc[col_idx]) if col_idx < len(sub_header) else ''
            if sub_text and sub_text != col_text:
                # Merge sub-header info if it has requirement
                if '(' in sub_text or 'max' in sub_text.lower() or 'min' in sub_text.lower():
                    col_text = col_text + ' ' + sub_text

        name, req = parse_requirement(col_text)
        if not name:
            continue

        kod = map_param_to_kod(name, req)
        if kod is None:
            # Try again with different parsing
            kod = map_param_to_kod(col_text, req)
        if kod is None:
            print(f"  UNMAPPED: {sheet_name} -> {col_text!r}")
            continue

        params.append({
            'kod': kod,
            'raw_name': name,
            'requirement': req,
        })

    return {
        'product': product_name,
        'spec_number': spec,
        'params': params,
    }


def parse_alkinol_sheet(df):
    """Parse the combined Alkinol/Alkinol_B sheet from poziome."""
    spec = extract_spec_number(df.iloc[0].values)
    header = df.iloc[1]

    results = []
    for product in ['Alkinol', 'Alkinol_B']:
        params = []
        for col_idx in range(len(header)):
            col_text = clean_text(header.iloc[col_idx])
            if not col_text:
                continue
            skip = False
            for sc in SKIP_COLS:
                if sc.upper() in col_text.upper():
                    skip = True
                    break
            if skip:
                continue

            name, req = parse_requirement(col_text)
            if not name:
                continue

            # Alkinol B specific: L.Jodowa only for Alkinol_B
            if 'JODOW' in col_text.upper() and product == 'Alkinol':
                continue
            # L.HYDROKS has different ranges
            if 'HYDROKS' in col_text.upper():
                if product == 'Alkinol':
                    req = '135-160'
                else:
                    req = '155-180'

            kod = map_param_to_kod(name, req)
            if kod is None:
                kod = map_param_to_kod(col_text, req)
            if kod is None:
                continue

            params.append({'kod': kod, 'raw_name': name, 'requirement': req})

        results.append({
            'product': product,
            'spec_number': spec,
            'params': params,
        })

    return results


def parse_monamid_ko(sheet_name, df):
    """Parse Monamid_KO / Monamid_KO_Revada sheets which have multi-row headers."""
    product_name = SHEET_TO_PRODUCT[sheet_name]

    spec = None
    for i in range(min(5, len(df))):
        s = extract_spec_number(df.iloc[i].values)
        if s:
            spec = s
            break

    # Find the main header row (with NUMER PARTII)
    header_row_idx = None
    for i in range(min(6, len(df))):
        row_vals = [clean_text(v) for v in df.iloc[i]]
        if any('NUMER PARTII' in v for v in row_vals):
            header_row_idx = i
            break

    if header_row_idx is None:
        return None

    header = df.iloc[header_row_idx]
    sub_header = df.iloc[header_row_idx + 1] if header_row_idx + 1 < len(df) else None

    params = []
    for col_idx in range(len(header)):
        col_text = clean_text(header.iloc[col_idx])
        sub_text = clean_text(sub_header.iloc[col_idx]) if sub_header is not None and col_idx < len(sub_header) else ''

        # Merge sub-header
        combined = col_text
        if sub_text and sub_text != col_text:
            combined = col_text + ' ' + sub_text

        if not combined:
            continue

        skip = False
        for sc in SKIP_COLS:
            if sc.upper() in combined.upper():
                skip = True
                break
        if skip:
            continue

        # WKT from sub-header
        if 'WKT' in combined.upper():
            name, req = parse_requirement(combined)
            if not req:
                # Try from sub
                _, req = parse_requirement(sub_text)
            params.append({'kod': 'wkt', 'raw_name': '% WKT', 'requirement': req})
            continue

        name, req = parse_requirement(combined)
        if not name:
            continue

        kod = map_param_to_kod(name, req)
        if kod is None:
            kod = map_param_to_kod(combined, req)
        if kod is None:
            if 'M. KW. LAURYN' not in combined and 'L. KW' not in combined and 'MMKO' not in combined:
                print(f"  UNMAPPED: {sheet_name} -> {combined!r}")
            continue

        params.append({'kod': kod, 'raw_name': name, 'requirement': req})

    return {
        'product': product_name,
        'spec_number': spec,
        'params': params,
    }


def main():
    print("=" * 60)
    print("Extracting parameters from ODS spreadsheets")
    print("=" * 60)

    # Read all sheets
    print("\nReading pionowe...")
    pionowe = pd.read_excel(str(PIONOWE), engine='odf', sheet_name=None, header=None)
    print(f"  Found {len(pionowe)} sheets")

    print("\nReading poziome...")
    poziome = pd.read_excel(str(POZIOME), engine='odf', sheet_name=None, header=None)
    print(f"  Found {len(poziome)} sheets")

    # Parse all sheets
    all_products = {}  # product_name -> {spec, params: [{kod, requirement}]}

    print("\n--- Parsing PIONOWE ---")
    for sheet_name, df in pionowe.items():
        if sheet_name in SKIP_SHEETS:
            continue
        print(f"  Parsing sheet: {sheet_name}")
        result = parse_sheet_pionowe(sheet_name, df)
        if result:
            pname = result['product']
            if pname not in all_products:
                all_products[pname] = {'spec_number': result['spec_number'], 'params': {}}
            elif result['spec_number'] and not all_products[pname]['spec_number']:
                all_products[pname]['spec_number'] = result['spec_number']
            for p in result['params']:
                key = p['kod']
                if key not in all_products[pname]['params']:
                    all_products[pname]['params'][key] = p

    print("\n--- Parsing POZIOME ---")
    for sheet_name, df in poziome.items():
        if sheet_name in SKIP_SHEETS:
            continue
        print(f"  Parsing sheet: {sheet_name}")

        # Special cases
        if sheet_name == 'Alkinol_Alkinol_B_':
            results = parse_alkinol_sheet(df)
            for result in results:
                pname = result['product']
                if pname not in all_products:
                    all_products[pname] = {'spec_number': result['spec_number'], 'params': {}}
                for p in result['params']:
                    if p['kod'] not in all_products[pname]['params']:
                        all_products[pname]['params'][p['kod']] = p
            continue

        if sheet_name in ('Monamid_KO', 'Monamid_KO_Revada'):
            result = parse_monamid_ko(sheet_name, df)
            if result:
                pname = result['product']
                if pname not in all_products:
                    all_products[pname] = {'spec_number': result['spec_number'], 'params': {}}
                elif result['spec_number'] and not all_products[pname].get('spec_number'):
                    all_products[pname]['spec_number'] = result['spec_number']
                for p in result['params']:
                    if p['kod'] not in all_products[pname]['params']:
                        all_products[pname]['params'][p['kod']] = p
            continue

        if sheet_name == 'Arkusz3':
            continue

        result = parse_sheet_pionowe(sheet_name, df)
        if result:
            pname = result['product']
            if pname not in all_products:
                all_products[pname] = {'spec_number': result['spec_number'], 'params': {}}
            elif result['spec_number'] and not all_products[pname].get('spec_number'):
                all_products[pname]['spec_number'] = result['spec_number']
            for p in result['params']:
                key = p['kod']
                if key not in all_products[pname]['params']:
                    all_products[pname]['params'][key] = p

    # Summary of extracted data
    print("\n" + "=" * 60)
    print("EXTRACTED DATA SUMMARY")
    print("=" * 60)
    for pname, data in sorted(all_products.items()):
        params_str = ', '.join(sorted(data['params'].keys()))
        print(f"  {pname} (spec={data['spec_number']}): {params_str}")

    # Connect to DB
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")

    stats = {
        'products_created': [],
        'products_updated_spec': [],
        'params_created': [],
        'cert_params_added': [],
        'cert_params_updated_req': [],
        'cert_variants_created': [],
        'typy_updated': [],
    }

    # Get existing products
    existing_products = {r['nazwa']: dict(r) for r in db.execute("SELECT * FROM produkty")}

    # Get existing parametry_analityczne
    existing_params = {r['kod']: dict(r) for r in db.execute("SELECT * FROM parametry_analityczne")}

    # Get existing parametry_cert (base variant)
    existing_cert_params = {}
    for r in db.execute("""
        SELECT pc.*, pa.kod as param_kod
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pc.parametr_id = pa.id
        WHERE pc.variant_id IS NULL
    """):
        key = (r['produkt'], r['param_kod'])
        existing_cert_params[key] = dict(r)

    # Get existing cert_variants
    existing_variants = {}
    for r in db.execute("SELECT * FROM cert_variants"):
        existing_variants[(r['produkt'], r['variant_id'])] = dict(r)

    # Process each product
    for product_name, data in sorted(all_products.items()):
        spec = data['spec_number']
        params = data['params']

        # 1. Ensure product exists
        if product_name not in existing_products:
            print(f"\n  CREATING product: {product_name}")
            display_name = product_name.replace('_', ' ')
            db.execute(
                "INSERT INTO produkty (nazwa, kod, aktywny, typy, display_name, spec_number) VALUES (?, ?, 1, ?, ?, ?)",
                (product_name, None, '["szarza"]', display_name, spec)
            )
            stats['products_created'].append(product_name)
            existing_products[product_name] = {'nazwa': product_name, 'spec_number': spec}
        elif spec and not existing_products[product_name].get('spec_number'):
            db.execute("UPDATE produkty SET spec_number = ? WHERE nazwa = ?", (spec, product_name))
            stats['products_updated_spec'].append(f"{product_name} -> {spec}")

        # 2. Ensure base cert_variant exists
        if (product_name, 'base') not in existing_variants:
            display_name = product_name.replace('_', ' ')
            db.execute(
                "INSERT INTO cert_variants (produkt, variant_id, label, spec_number) VALUES (?, 'base', ?, ?)",
                (product_name, display_name, spec)
            )
            stats['cert_variants_created'].append(product_name)
            existing_variants[(product_name, 'base')] = {'produkt': product_name, 'variant_id': 'base'}

        # 3. Process parameters
        for param_kod, param_data in params.items():
            req = param_data.get('requirement')

            # Ensure parametr_analityczny exists
            if param_kod not in existing_params:
                label = param_data['raw_name']
                print(f"  CREATING parametr_analityczny: {param_kod} ({label})")
                cursor = db.execute(
                    "INSERT INTO parametry_analityczne (kod, label, typ) VALUES (?, ?, 'bezposredni')",
                    (param_kod, label)
                )
                existing_params[param_kod] = {'id': cursor.lastrowid, 'kod': param_kod, 'label': label}
                stats['params_created'].append(param_kod)

            param_id = existing_params[param_kod]['id']

            # Check if parametry_cert entry exists (base variant, variant_id IS NULL)
            key = (product_name, param_kod)
            if key not in existing_cert_params:
                # Count existing params to determine kolejnosc
                max_order = db.execute(
                    "SELECT COALESCE(MAX(kolejnosc), 0) FROM parametry_cert WHERE produkt = ? AND variant_id IS NULL",
                    (product_name,)
                ).fetchone()[0]

                db.execute(
                    "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement) VALUES (?, ?, ?, ?)",
                    (product_name, param_id, max_order + 1, req)
                )
                stats['cert_params_added'].append(f"{product_name}.{param_kod}")
                existing_cert_params[key] = {'requirement': req}
            else:
                # Update requirement if different and current is NULL
                existing_req = existing_cert_params[key].get('requirement')
                if req and not existing_req:
                    db.execute(
                        "UPDATE parametry_cert SET requirement = ? WHERE produkt = ? AND parametr_id = ? AND variant_id IS NULL",
                        (req, product_name, param_id)
                    )
                    stats['cert_params_updated_req'].append(f"{product_name}.{param_kod}: NULL -> {req}")
                elif req and existing_req and req != existing_req:
                    # Requirement differs - DON'T overwrite existing; cert DB has authoritative values
                    # Only log for informational purposes
                    pass  # stats['cert_params_updated_req'].append(f"{product_name}.{param_kod}: {existing_req} vs ODS {req}")

    # 4. Update typy for platkowanie products
    platk_products = ['HSH_CS_3070', 'Chemal_CS_3070', 'Monamid_KO', 'Alkinol', 'Alkinol_B']
    for pname in platk_products:
        row = db.execute("SELECT typy FROM produkty WHERE nazwa = ?", (pname,)).fetchone()
        if row:
            typy = json.loads(row['typy']) if row['typy'] else []
            if 'platkowanie' not in typy:
                typy.append('platkowanie')
                db.execute("UPDATE produkty SET typy = ? WHERE nazwa = ?", (json.dumps(typy), pname))
                stats['typy_updated'].append(pname)

    db.commit()

    # Print summary
    print("\n" + "=" * 60)
    print("DATABASE UPDATE SUMMARY")
    print("=" * 60)

    print(f"\nProducts created ({len(stats['products_created'])}):")
    for p in stats['products_created']:
        print(f"  + {p}")

    print(f"\nProducts spec_number updated ({len(stats['products_updated_spec'])}):")
    for p in stats['products_updated_spec']:
        print(f"  ~ {p}")

    print(f"\nParametry_analityczne created ({len(stats['params_created'])}):")
    for p in stats['params_created']:
        print(f"  + {p}")

    print(f"\nCert_variants created ({len(stats['cert_variants_created'])}):")
    for p in stats['cert_variants_created']:
        print(f"  + {p} (base)")

    print(f"\nParametry_cert added ({len(stats['cert_params_added'])}):")
    for p in stats['cert_params_added']:
        print(f"  + {p}")

    print(f"\nParametry_cert requirements updated ({len(stats['cert_params_updated_req'])}):")
    for p in stats['cert_params_updated_req']:
        print(f"  ~ {p}")

    print(f"\nTypy updated with 'platkowanie' ({len(stats['typy_updated'])}):")
    for p in stats['typy_updated']:
        print(f"  ~ {p}")

    db.close()

    # Regenerate cert_config.json
    print("\n" + "=" * 60)
    print("Regenerating cert_config.json...")
    import sys
    sys.path.insert(0, '.')
    from mbr.db import db_session
    from mbr.certs.generator import save_cert_config_export
    with db_session() as dbx:
        save_cert_config_export(dbx)
    print("Done!")


if __name__ == '__main__':
    main()
