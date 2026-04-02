/**
 * calculator.js — Titration calculator for lab fast-entry.
 * Supports any parameter with calc_method (dynamic), plus legacy hardcoded fallbacks.
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
    method: null,
    samples: [{m: '', v: ''}, {m: '', v: ''}],
};

function openCalculator(tag, kod, sekcja, calcMethod) {
    // If calcMethod provided (from pole.calc_method), use it. Otherwise fall back to CALC_METHODS.
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

    _calcState.tag = tag;
    _calcState.kod = kod;
    _calcState.sekcja = sekcja;
    _calcState.method = method;
    _calcState.samples = [{m: '', v: ''}, {m: '', v: ''}];

    renderCalculator();
}

function renderCalculator() {
    const container = document.getElementById('calc-container');
    const method = _calcState.method || CALC_METHODS[_calcState.tag];
    if (!method) {
        container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;">Kliknij pole miareczkowe aby otworzyc kalkulator.</div>';
        return;
    }

    let html = '';

    // Header
    html += `
        <div class="calc-header">
            <div class="calc-param">${method.name}</div>
            <div class="calc-method">${method.method}</div>
            <div class="calc-formula">${method.formula}</div>
        </div>
    `;

    // Samples
    _calcState.samples.forEach((sample, i) => {
        const result = calcSample(sample, method);
        html += `
            <div class="calc-sample">
                <div class="cs-head">
                    <div class="cs-num">${i + 1}</div>
                    <div class="cs-label">Probka ${i + 1}</div>
                    <div class="cs-result-tag">${result !== null ? result.toFixed(3) : '---'}</div>
                </div>
                <div class="cs-fields">
                    <div class="cs-field">
                        <label>Nawazka [g]</label>
                        <input type="number" step="any" value="${sample.m}"
                            oninput="updateSample(${i}, 'm', this.value)">
                    </div>
                    <div class="cs-field">
                        <label>V titranta [ml]</label>
                        <input type="number" step="any" value="${sample.v}"
                            oninput="updateSample(${i}, 'v', this.value)">
                    </div>
                </div>
            </div>
        `;
    });

    // Add sample button
    html += `<button class="calc-add" onclick="addSample()">+ Dodaj probke</button>`;

    // Summary
    const results = _calcState.samples
        .map(s => calcSample(s, method))
        .filter(r => r !== null);

    if (results.length > 0) {
        const avg = results.reduce((a, b) => a + b, 0) / results.length;
        let convHtml = '';
        if (results.length >= 2) {
            const maxR = Math.max(...results);
            const minR = Math.min(...results);
            const delta = maxR - minR;
            const deltaPercent = avg > 0 ? (delta / avg) * 100 : 0;
            const isConvergent = deltaPercent < 0.5;
            convHtml = `<div class="calc-convergence${isConvergent ? ' ok' : ''}">${isConvergent ? 'Zbiezne' : 'Niezbiezne'} (delta ${deltaPercent.toFixed(2)}%)</div>`;
        }

        html += `
            <div class="calc-summary">
                <div>
                    <div class="calc-avg-label">Srednia</div>
                    ${convHtml}
                </div>
                <div class="calc-avg-value">${avg.toFixed(3)}</div>
            </div>
        `;

        // Accept button
        html += `<button class="calc-accept" onclick="acceptCalc()">Zatwierdz wynik &rarr; ${method.name}</button>`;
    }

    container.innerHTML = html;
}

function calcSample(sample, method) {
    const m = parseFloat(sample.m);
    const v = parseFloat(sample.v);
    if (isNaN(m) || isNaN(v) || m === 0) return null;
    return (v * method.factor) / m;
}

function updateSample(index, field, value) {
    _calcState.samples[index][field] = value;
    renderCalculator();
}

function addSample() {
    _calcState.samples.push({m: '', v: ''});
    renderCalculator();
}

function acceptCalc() {
    const method = _calcState.method || CALC_METHODS[_calcState.tag];
    if (!method) return;

    const results = _calcState.samples
        .map(s => calcSample(s, method))
        .filter(r => r !== null);
    if (results.length === 0) return;

    const avg = results.reduce((a, b) => a + b, 0) / results.length;

    // Write to main form field
    const input = document.querySelector(
        `input[data-kod="${_calcState.kod}"][data-sekcja="${_calcState.sekcja}"]`
    );
    if (input) {
        // Round to reasonable precision
        input.value = avg.toFixed(3);
        input.classList.add('calc');
        // Trigger validation
        if (typeof validateField === 'function') {
            validateField(input);
        }
    }
}

// Aliases matching spec naming
function openCalc(tag, kod, sekcja, calcMethod) { openCalculator(tag, kod, sekcja, calcMethod); }
function recalc() { renderCalculator(); }

// Export
window.openCalculator = openCalculator;
window.openCalc = openCalc;
window.recalc = recalc;
window.acceptCalc = acceptCalc;
