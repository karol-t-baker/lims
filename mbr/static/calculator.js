/**
 * calculator.js — Persistent titration calculator for lab fast-entry.
 * Supports any parameter with calc_method (dynamic), plus legacy hardcoded fallbacks.
 *
 * Workflow:
 *   1. Operator enters nawazki (masses) -> auto-saved to DB (debounced 1s)
 *   2. Operator can switch batches, close browser, come back later
 *   3. Operator enters objetosci (volumes) -> result auto-calculated, auto-saved
 *   4. "Zatwierdz wynik" writes average to form field + saves complete samples
 */

if (typeof CALC_METHODS !== 'undefined') { /* already loaded */ } else {

// CALC_METHODS loaded from /api/parametry/calc-methods at page load.
// Legacy tag-based keys (procent_*) are generated as aliases for backward compatibility.
var CALC_METHODS = {};

(function loadCalcMethods() {
    fetch('/api/parametry/calc-methods')
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            // data = {kod: {name, method, formula, factor}}
            for (var kod in data) {
                var m = data[kod];
                CALC_METHODS[kod] = m;
                // Legacy aliases: tag-based keys used by old parametry_lab format
                CALC_METHODS['procent_' + kod] = m;
            }
        })
        .catch(function() {
            // Fallback: hardcoded methods if API fails (e.g. not logged in)
            CALC_METHODS = {
                nacl:  { name: '%NaCl', method: 'Argentometryczna Mohr', formula: '% = (V * 0.00585 * 100) / m', factor: 0.585 },
                aa:    { name: '%AA',   method: 'Alkacymetria',          formula: '% = (V * C * M) / (m * 10)',   factor: 3.015 },
                so3:   { name: '%SO3',  method: 'Jodometryczna',         formula: '% = (V * 0.004 * 100) / m',   factor: 0.4 },
                h2o2:  { name: '%H2O2', method: 'Manganometryczna',      formula: '% = (V * 0.0017 * 100) / m',  factor: 0.17 },
                lk:    { name: 'LK',    method: 'Alkacymetria KOH',      formula: 'LK = (V * C * 56.1) / m',     factor: 5.61 },
            };
            for (var k in CALC_METHODS) {
                CALC_METHODS['procent_' + k] = CALC_METHODS[k];
            }
        });
})();

let _calcState = {
    tag: null,
    kod: null,
    sekcja: null,
    ebrId: null,
    method: null,
    samples: [{m: '', v: ''}, {m: '', v: ''}],
    loading: false,
};

let _saveTimeout = null;
let _saveIndicatorTimeout = null;

function scheduleSave() {
    clearTimeout(_saveTimeout);
    showSaveStatus('saving');
    _saveTimeout = setTimeout(async () => {
        await doSaveSamples();
        showSaveStatus('saved');
    }, 1000);
}

function showSaveStatus(status) {
    const el = document.getElementById('calc-save-status');
    if (!el) return;
    clearTimeout(_saveIndicatorTimeout);
    if (status === 'saving') {
        el.textContent = 'Zapisywanie...';
        el.style.color = 'var(--text-dim)';
        el.style.opacity = '1';
    } else if (status === 'saved') {
        el.textContent = '\u2713 Zapisano';
        el.style.color = 'var(--green)';
        el.style.opacity = '1';
        _saveIndicatorTimeout = setTimeout(() => { el.style.opacity = '0'; }, 2000);
    } else if (status === 'error') {
        el.textContent = 'Blad zapisu';
        el.style.color = 'var(--red)';
        el.style.opacity = '1';
        _saveIndicatorTimeout = setTimeout(() => { el.style.opacity = '0'; }, 3000);
    }
}

async function doSaveSamples() {
    try {
        const resp = await fetch(`/api/ebr/${_calcState.ebrId}/samples`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sekcja: _calcState.sekcja,
                kod_parametru: _calcState.kod,
                tag: _calcState.tag || '',
                samples: _calcState.samples
            })
        });
        if (!resp.ok) {
            showSaveStatus('error');
            return;
        }
    } catch(e) {
        showSaveStatus('error');
    }
}

async function openCalculator(tag, kod, sekcja, calcMethod) {
    // Determine method
    let method;
    if (calcMethod && calcMethod.factor) {
        method = {
            name: calcMethod.name || kod,
            method: calcMethod.name || '',
            formula: calcMethod.formula || '',
            factor: calcMethod.factor,
            suggested_mass: calcMethod.suggested_mass || null,
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

/**
 * Lightweight update: only refreshes result tags, summary, and accept button
 * without rebuilding inputs (preserves focus and cursor position).
 */
function updateResults() {
    const method = _calcState.method;
    if (!method) return;

    // Update each sample's result tag
    _calcState.samples.forEach((s, i) => {
        const r = calcSample(s, method);
        const tag = document.getElementById(`cs-result-${i}`);
        if (tag) tag.textContent = r !== null ? r.toFixed(3) : '---';
    });

    // Gather results
    const results = _calcState.samples.map(s => calcSample(s, method)).filter(r => r !== null);

    // Update summary area
    const summaryEl = document.getElementById('calc-summary-area');
    if (summaryEl) {
        if (results.length >= 2) {
            const avg = results.reduce((a, b) => a + b, 0) / results.length;
            const delta = Math.max(...results) - Math.min(...results);
            const convergent = delta < 0.5;
            summaryEl.innerHTML = `<div class="calc-summary">
                <div><div class="calc-avg-label">Srednia</div>
                <div class="calc-convergence ${convergent ? 'ok' : ''}">\u0394 = ${delta.toFixed(3)} \u2014 ${convergent ? 'zbiezne' : 'BRAK ZBIEZNOSCI'}</div></div>
                <div class="calc-avg-value">${avg.toFixed(3)}</div>
            </div>`;
        } else if (results.length === 1) {
            summaryEl.innerHTML = `<div class="calc-summary">
                <div><div class="calc-avg-label">Wynik</div>
                <div class="calc-convergence">Jedna probka \u2014 dodaj druga</div></div>
                <div class="calc-avg-value">${results[0].toFixed(3)}</div>
            </div>`;
        } else {
            summaryEl.innerHTML = '';
        }
    }

    // Update accept button visibility
    const acceptBtn = document.getElementById('calc-accept-btn');
    if (acceptBtn) acceptBtn.style.display = results.length >= 1 ? 'block' : 'none';

    // Update saved-masses hint
    const savedMasses = _calcState.samples.filter(s => s.m && !s.v).length;
    const hintEl = document.getElementById('calc-masses-hint');
    if (hintEl) {
        if (savedMasses > 0) {
            hintEl.textContent = `${savedMasses} probek z zapisana nawazka \u2014 uzupelnij objetosci`;
            hintEl.style.display = 'block';
        } else {
            hintEl.style.display = 'none';
        }
    }
}

/**
 * Called from oninput on sample fields. Updates state, refreshes results
 * without full re-render, and schedules auto-save.
 */
function onSampleInput(sampleIndex, field, value) {
    _calcState.samples[sampleIndex][field] = value;
    updateResults();
    scheduleSave();
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

    // Suggested mass hint
    if (method.suggested_mass) {
        html += `<div class="calc-hint">Sugerowana naważka: <strong>${method.suggested_mass} g</strong></div>`;
    }

    // Samples
    const results = [];
    _calcState.samples.forEach((s, i) => {
        const r = calcSample(s, method);
        if (r !== null) results.push(r);

        html += `<div class="calc-sample">
            <div class="cs-head">
                <div class="cs-num">${i + 1}</div>
                <span class="cs-label">Probka</span>
                <span class="cs-result-tag" id="cs-result-${i}">${r !== null ? r.toFixed(3) : '---'}</span>
            </div>
            <div class="cs-fields">
                <div class="cs-field">
                    <label>Nawazka [g]</label>
                    <input type="number" step="any" value="${s.m || ''}"
                        oninput="onSampleInput(${i}, 'm', this.value)"
                        placeholder="---">
                </div>
                <div class="cs-field">
                    <label>V titranta [ml]</label>
                    <input type="number" step="any" value="${s.v || ''}"
                        oninput="onSampleInput(${i}, 'v', this.value)"
                        placeholder="---">
                </div>
            </div>
        </div>`;
    });

    // Add sample button
    html += `<button class="calc-add" onclick="addSample()">+ Dodaj probke</button>`;

    // Summary area (updated by updateResults without full re-render)
    html += `<div id="calc-summary-area">`;
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
    html += `</div>`;

    // Accept button
    const hasResult = results.length >= 1;
    html += `<button class="calc-accept" id="calc-accept-btn" style="display:${hasResult ? 'block' : 'none'};margin-top:10px;" onclick="acceptCalc()">Zatwierdz wynik \u2192</button>`;

    // Save status indicator
    html += `<div id="calc-save-status" class="calc-save-status"></div>`;

    // Saved-masses hint
    const savedMasses = _calcState.samples.filter(s => s.m && !s.v).length;
    html += `<div id="calc-masses-hint" style="text-align:center;margin-top:8px;font-size:10px;color:var(--amber);display:${savedMasses > 0 ? 'block' : 'none'};">${savedMasses > 0 ? savedMasses + ' probek z zapisana nawazka \u2014 uzupelnij objetosci' : ''}</div>`;

    container.innerHTML = html;
}

function addSample() {
    _calcState.samples.push({m: '', v: ''});
    renderCalculator();
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
    await doSaveSamples();
    showSaveStatus('saved');
}

// Aliases matching spec naming
function openCalc(tag, kod, sekcja, calcMethod) { openCalculator(tag, kod, sekcja, calcMethod); }
function recalc() { renderCalculator(); }

// Export
window.openCalculator = openCalculator;
window.openCalc = openCalc;
window.recalc = recalc;
window.acceptCalc = acceptCalc;
window.addSample = addSample;
window.onSampleInput = onSampleInput;

} // end guard: CALC_METHODS already defined
