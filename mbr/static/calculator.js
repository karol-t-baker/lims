/**
 * calculator.js — Persistent titration calculator for lab fast-entry.
 * Supports any parameter with calc_method (dynamic), plus legacy hardcoded fallbacks.
 *
 * Workflow:
 *   1. Operator enters naważki (masses) -> "Zapisz naważki" saves to DB
 *   2. Operator can switch batches, close browser, come back later
 *   3. Operator enters objętości (volumes) -> result auto-calculated
 *   4. "Zatwierdź wynik" writes average to form field + saves complete samples
 */

const CALC_METHODS = {
    procent_sa:   { name: '%SA',   method: 'Dwufazowa Epton',      formula: '% = (V * C * M) / (m * 10)', factor: 3.261 },
    procent_nacl: { name: '%NaCl', method: 'Argentometryczna Mohr', formula: '% = (V * 0.00585 * 100) / m', factor: 0.585 },
    procent_aa:   { name: '%AA',   method: 'Alkacymetria',          formula: '% = (V * C * M) / (m * 10)', factor: 3.015 },
    procent_so3:  { name: '%SO3',  method: 'Jodometryczna',         formula: '% = (V * 0.004 * 100) / m',  factor: 0.4 },
    procent_h2o2: { name: '%H2O2', method: 'Manganometryczna',      formula: '% = (V * 0.0017 * 100) / m', factor: 0.17 },
    lk:                 { name: 'LK',    method: 'Alkacymetria KOH',      formula: 'LK = (V * C * 56.1) / m',    factor: 5.61 },
    le_liczba_kwasowa:  { name: 'LK',    method: 'Alkacymetria KOH',      formula: 'LK = (V * C * 56.1) / m',    factor: 5.61 },
};

let _calcState = {
    tag: null,
    kod: null,
    sekcja: null,
    ebrId: null,
    method: null,
    samples: [{m: '', v: ''}, {m: '', v: ''}],
    loading: false,
};

async function openCalculator(tag, kod, sekcja, calcMethod) {
    // Determine method
    let method;
    if (calcMethod && calcMethod.factor) {
        method = {
            name: calcMethod.name || kod,
            method: calcMethod.name || '',
            formula: calcMethod.formula || '',
            factor: calcMethod.factor,
        };
    } else {
        method = CALC_METHODS[tag] || CALC_METHODS[kod];
    }
    if (!method) return;

    _calcState = {
        tag: tag,
        kod: kod,
        sekcja: sekcja,
        ebrId: window.ebrId,
        method: method,
        samples: [{m: '', v: ''}, {m: '', v: ''}],
        loading: true,
    };

    // Show calc tab
    if (typeof showRightPanel === 'function') showRightPanel('calc');

    // Highlight active field
    document.querySelectorAll('.ff.titr').forEach(f => f.classList.remove('active-calc'));
    const activeField = document.querySelector(`.ff.titr input[data-kod="${kod}"][data-sekcja="${sekcja}"]`);
    if (activeField) {
        const ff = activeField.closest('.ff.titr');
        if (ff) ff.classList.add('active-calc');
    }

    renderCalculator(); // Show loading state

    // Load saved samples from server
    try {
        const resp = await fetch(`/api/ebr/${_calcState.ebrId}/samples/${sekcja}/${kod}`);
        const data = await resp.json();
        if (data.samples && data.samples.length > 0) {
            _calcState.samples = data.samples;
        }
    } catch(e) {
        // use defaults
    }

    _calcState.loading = false;
    renderCalculator();
}

function calcSample(sample, method) {
    const m = parseFloat(sample.m);
    const v = parseFloat(sample.v);
    if (isNaN(m) || isNaN(v) || m === 0) return null;
    return (v * method.factor) / m;
}

function renderCalculator() {
    const container = document.getElementById('calc-container');
    const method = _calcState.method;
    if (!method) {
        container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;">Kliknij pole miareczkowe aby otworzyc kalkulator.</div>';
        return;
    }

    if (_calcState.loading) {
        container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;">Ladowanie...</div>';
        return;
    }

    let html = '';

    // Header
    html += `<div class="calc-header">
        <div class="calc-param">${method.name}</div>
        <div class="calc-method">Metoda: ${method.method || method.name}</div>
        <div class="calc-formula">${method.formula}</div>
    </div>`;

    // Samples
    const results = [];
    _calcState.samples.forEach((s, i) => {
        const r = calcSample(s, method);
        if (r !== null) results.push(r);

        html += `<div class="calc-sample">
            <div class="cs-head">
                <div class="cs-num">${i + 1}</div>
                <span class="cs-label">Probka</span>
                <span class="cs-result-tag">${r !== null ? r.toFixed(3) : '---'}</span>
            </div>
            <div class="cs-fields">
                <div class="cs-field">
                    <label>Nawazka [g]</label>
                    <input type="number" step="any" value="${s.m || ''}"
                        oninput="_calcState.samples[${i}].m=this.value;renderCalculator();"
                        placeholder="---">
                </div>
                <div class="cs-field">
                    <label>V titranta [ml]</label>
                    <input type="number" step="any" value="${s.v || ''}"
                        oninput="_calcState.samples[${i}].v=this.value;renderCalculator();"
                        placeholder="---">
                </div>
            </div>
        </div>`;
    });

    // Add sample button
    html += `<button class="calc-add" onclick="addSample()">+ Dodaj probke</button>`;

    // Summary
    if (results.length >= 2) {
        const avg = results.reduce((a, b) => a + b, 0) / results.length;
        const delta = Math.max(...results) - Math.min(...results);
        const convergent = delta < 0.5;
        html += `<div class="calc-summary">
            <div>
                <div class="calc-avg-label">Srednia</div>
                <div class="calc-convergence ${convergent ? 'ok' : ''}">
                    \u0394 = ${delta.toFixed(3)} \u2014 ${convergent ? 'zbiezne' : 'BRAK ZBIEZNOSCI'}
                </div>
            </div>
            <div class="calc-avg-value">${avg.toFixed(3)}</div>
        </div>`;
    } else if (results.length === 1) {
        html += `<div class="calc-summary">
            <div>
                <div class="calc-avg-label">Wynik</div>
                <div class="calc-convergence">Jedna probka \u2014 dodaj druga</div>
            </div>
            <div class="calc-avg-value">${results[0].toFixed(3)}</div>
        </div>`;
    }

    // Buttons
    const hasAnyMass = _calcState.samples.some(s => s.m);
    const hasResult = results.length >= 1;

    html += `<div style="display:flex;gap:8px;margin-top:10px;">`;
    if (hasAnyMass) {
        html += `<button class="calc-add" id="btn-save-nawazki" style="flex:1;border-style:solid;border-color:var(--teal);color:var(--teal);" onclick="saveSamples()">Zapisz nawazki</button>`;
    }
    if (hasResult) {
        html += `<button class="calc-accept" style="flex:1;" onclick="acceptCalc()">Zatwierdz wynik \u2192</button>`;
    }
    html += `</div>`;

    // Status indicator: show if samples were loaded from DB with masses but no volumes
    const savedMasses = _calcState.samples.filter(s => s.m && !s.v).length;
    if (savedMasses > 0) {
        html += `<div style="text-align:center;margin-top:8px;font-size:10px;color:var(--amber);">${savedMasses} probek z zapisana nawazka \u2014 uzupelnij objetosci</div>`;
    }

    container.innerHTML = html;
}

function addSample() {
    _calcState.samples.push({m: '', v: ''});
    renderCalculator();
}

async function saveSamples() {
    try {
        await fetch(`/api/ebr/${_calcState.ebrId}/samples`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sekcja: _calcState.sekcja,
                kod_parametru: _calcState.kod,
                tag: _calcState.tag || '',
                samples: _calcState.samples
            })
        });
        // Show brief confirmation
        const btn = document.getElementById('btn-save-nawazki');
        if (btn) {
            const orig = btn.textContent;
            btn.textContent = '\u2713 Zapisano';
            btn.style.background = 'var(--green-bg)';
            btn.style.color = 'var(--green)';
            setTimeout(() => {
                btn.textContent = orig;
                btn.style.background = '';
                btn.style.color = 'var(--teal)';
            }, 1500);
        }
    } catch(e) {
        alert('Blad zapisu nawazek');
    }
}

async function acceptCalc() {
    const method = _calcState.method;
    if (!method) return;

    const results = _calcState.samples
        .map(s => calcSample(s, method))
        .filter(r => r !== null);
    if (results.length === 0) return;

    const avg = results.reduce((a, b) => a + b, 0) / results.length;

    // Write to form field
    const input = document.querySelector(
        `input[data-kod="${_calcState.kod}"][data-sekcja="${_calcState.sekcja}"]`
    );
    if (input) {
        input.value = avg.toFixed(3);
        input.classList.add('calc');
        if (typeof validateField === 'function') {
            validateField(input);
        }
    }

    // Save complete samples (with volumes) to DB
    await saveSamples();
}

// Aliases matching spec naming
function openCalc(tag, kod, sekcja, calcMethod) { openCalculator(tag, kod, sekcja, calcMethod); }
function recalc() { renderCalculator(); }

// Export
window.openCalculator = openCalculator;
window.openCalc = openCalc;
window.recalc = recalc;
window.acceptCalc = acceptCalc;
window.saveSamples = saveSamples;
window.addSample = addSample;
