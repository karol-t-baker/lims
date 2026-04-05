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

function calcStats(results) {
    if (results.length < 2) return null;
    var n = results.length;
    var mean = results.reduce(function(a, b) { return a + b; }, 0) / n;
    var delta = Math.max.apply(null, results) - Math.min.apply(null, results);
    var variance = results.reduce(function(a, b) { return a + (b - mean) * (b - mean); }, 0) / (n - 1);
    var stdDev = Math.sqrt(variance);
    var rsd = mean !== 0 ? (stdDev / Math.abs(mean)) * 100 : 0;
    var rsm = rsd / Math.sqrt(n);
    return { mean: mean, delta: delta, stdDev: stdDev, rsd: rsd, rsm: rsm, convergent: delta < 0.5 };
}

var _calcTitrantValues = {};

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

async function openCalculatorFull(metoda_id, kod, sekcja) {
    var resp = await fetch('/api/metody-miareczkowe/' + metoda_id);
    if (!resp.ok) return;
    var method = await resp.json();

    _calcState = {
        tag: kod,
        kod: kod,
        sekcja: sekcja,
        ebrId: window.ebrId,
        method: {
            name: method.nazwa,
            method: method.nazwa,
            formula: method.formula,
            factor: null,
            suggested_mass: null,
            mass_required: method.mass_required,
            volumes: method.volumes || [],
            titrants: method.titrants || [],
        },
        samples: [{m: '', vols: [], on: true}, {m: '', vols: [], on: true}],
        loading: false,
        fullMethod: true,
    };

    // Init vols arrays to match volume count
    var nVols = _calcState.method.volumes.length;
    _calcState.samples.forEach(function(s) {
        s.vols = new Array(nVols).fill('');
    });

    // Init titrant values from defaults
    _calcState.method.titrants.forEach(function(t) {
        if (!_calcTitrantValues[t.id]) {
            _calcTitrantValues[t.id] = t.default || 0.1;
        }
    });

    // Highlight active field
    document.querySelectorAll('.ff.titr').forEach(f => f.classList.remove('active-calc'));
    const activeField = document.querySelector(`.ff.titr input[data-kod="${kod}"][data-sekcja="${sekcja}"]`);
    if (activeField) {
        const ff = activeField.closest('.ff.titr');
        if (ff) ff.classList.add('active-calc');
    }

    // Load saved samples
    try {
        var sResp = await fetch('/api/ebr/' + _calcState.ebrId + '/samples/' + sekcja + '/' + kod);
        var sData = await sResp.json();
        if (sData.samples && sData.samples.length > 0) {
            _calcState.samples = sData.samples.map(function(s) {
                return {
                    m: s.m || '',
                    vols: s.vols || new Array(nVols).fill(''),
                    on: true
                };
            });
        }
    } catch(e) {}

    renderCalculator();
}

function calcSample(sample, method) {
    const m = parseFloat(sample.m);
    const v = parseFloat(sample.v);
    if (isNaN(m) || isNaN(v) || m === 0) return null;
    return (v * method.factor) / m;
}

function calcSampleFull(sample, method) {
    if (!sample.on) return null;
    var vars = {};
    if (method.mass_required) {
        var m = parseFloat(sample.m);
        if (isNaN(m) || m === 0) return null;
        vars.M = m;
    }
    // Volumes
    for (var i = 0; i < method.volumes.length; i++) {
        var v = parseFloat(sample.vols[i]);
        if (isNaN(v)) return null;
        vars['V' + (i + 1)] = v;
    }
    // Titrants
    method.titrants.forEach(function(t) {
        vars[t.id] = _calcTitrantValues[t.id] || t.default || 0.1;
    });
    try {
        var keys = Object.keys(vars);
        var vals = keys.map(function(k) { return vars[k]; });
        var fn = new Function(keys.join(','), 'return (' + method.formula + ');');
        var r = fn.apply(null, vals);
        if (!isFinite(r) || isNaN(r)) return null;
        return r;
    } catch(e) { return null; }
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
            var stats = calcStats(results);
            summaryEl.innerHTML = '<div class="calc-summary">' +
                '<div><div class="calc-avg-label">\u015arednia</div>' +
                '<div class="calc-convergence ' + (stats.convergent ? 'ok' : '') + '">\u0394 = ' + stats.delta.toFixed(3) + ' \u2014 ' + (stats.convergent ? 'zbie\u017cne' : 'BRAK ZBIE\u017bNO\u015aCI') + '</div>' +
                '<div style="font-size:10px;color:var(--text-dim);font-family:var(--mono);margin-top:2px;">RSD = ' + stats.rsd.toFixed(2) + '%   RSM = ' + stats.rsm.toFixed(2) + '%</div>' +
                '</div>' +
                '<div class="calc-avg-value">' + stats.mean.toFixed(3) + '</div>' +
            '</div>';
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

function renderCalculatorFull() {
    const container = document.getElementById('calc-container');
    const method = _calcState.method;
    if (!method) return;

    let html = '';

    // Header
    html += `<div class="calc-header">
        <div class="calc-param">${method.name}</div>
        <div class="calc-formula">${method.formula}</div>
    </div>`;

    // Titrant inputs
    if (method.titrants && method.titrants.length > 0) {
        html += '<div style="margin-bottom:8px;">';
        method.titrants.forEach(function(t) {
            var val = _calcTitrantValues[t.id] !== undefined ? _calcTitrantValues[t.id] : (t.default || 0.1);
            if (t.options && t.options.length > 0) {
                html += '<div class="cs-field" style="margin-bottom:4px;"><label>' + (t.label || t.id) + '</label>';
                html += '<select onchange="_calcTitrantValues[\'' + t.id + '\'] = parseFloat(this.value); updateResultsFull();">';
                t.options.forEach(function(opt) {
                    var optVal = typeof opt === 'object' ? opt.value : opt;
                    var optLabel = typeof opt === 'object' ? opt.label : opt;
                    var sel = optVal == val ? ' selected' : '';
                    html += '<option value="' + optVal + '"' + sel + '>' + optLabel + '</option>';
                });
                html += '</select></div>';
            } else {
                html += '<div class="cs-field" style="margin-bottom:4px;"><label>' + (t.label || t.id) + '</label>';
                html += '<input type="number" step="any" value="' + val + '" oninput="_calcTitrantValues[\'' + t.id + '\'] = parseFloat(this.value); updateResultsFull();" placeholder="---"></div>';
            }
        });
        html += '</div>';
    }

    // Samples
    var results = [];
    _calcState.samples.forEach(function(s, i) {
        var r = calcSampleFull(s, method);
        if (r !== null) results.push(r);

        html += '<div class="calc-sample">';
        html += '<div class="cs-head">';
        html += '<div class="cs-num">' + (i + 1) + '</div>';
        html += '<span class="cs-label">Pr\u00f3bka</span>';
        html += '<span class="cs-result-tag" id="cs-result-' + i + '">' + (r !== null ? r.toFixed(3) : '---') + '</span>';
        html += '</div>';
        html += '<div class="cs-fields">';

        if (method.mass_required) {
            html += '<div class="cs-field"><label>Nawa\u017cka [g]</label>';
            html += '<input type="number" step="any" value="' + (s.m || '') + '" oninput="onSampleInputFull(' + i + ', \'m\', this.value)" placeholder="---"></div>';
        }

        method.volumes.forEach(function(vol, vi) {
            var label = vol.label || ('V' + (vi + 1) + ' [ml]');
            html += '<div class="cs-field"><label>' + label + '</label>';
            html += '<input type="number" step="any" value="' + (s.vols[vi] || '') + '" oninput="onSampleInputFull(' + i + ', ' + vi + ', this.value)" placeholder="---"></div>';
        });

        html += '</div></div>';
    });

    // Add sample button
    html += '<button class="calc-add" onclick="addSampleFull()">+ Dodaj pr\u00f3bk\u0119</button>';

    // Summary
    html += '<div id="calc-summary-area">';
    if (results.length >= 2) {
        var stats = calcStats(results);
        html += '<div class="calc-summary">' +
            '<div><div class="calc-avg-label">\u015arednia</div>' +
            '<div class="calc-convergence ' + (stats.convergent ? 'ok' : '') + '">\u0394 = ' + stats.delta.toFixed(3) + ' \u2014 ' + (stats.convergent ? 'zbie\u017cne' : 'BRAK ZBIE\u017bNO\u015aCI') + '</div>' +
            '<div style="font-size:10px;color:var(--text-dim);font-family:var(--mono);margin-top:2px;">RSD = ' + stats.rsd.toFixed(2) + '%   RSM = ' + stats.rsm.toFixed(2) + '%</div>' +
            '</div>' +
            '<div class="calc-avg-value">' + stats.mean.toFixed(3) + '</div>' +
        '</div>';
    } else if (results.length === 1) {
        html += '<div class="calc-summary"><div><div class="calc-avg-label">Wynik</div>' +
            '<div class="calc-convergence">Jedna pr\u00f3bka \u2014 dodaj drug\u0105</div></div>' +
            '<div class="calc-avg-value">' + results[0].toFixed(3) + '</div></div>';
    }
    html += '</div>';

    // Accept button
    html += '<button class="calc-accept" id="calc-accept-btn" style="display:' + (results.length >= 1 ? 'block' : 'none') + ';margin-top:10px;" onclick="acceptCalc()">Zatwierd\u017a wynik \u2192</button>';
    html += '<div id="calc-save-status" class="calc-save-status"></div>';

    container.innerHTML = html;
}

function onSampleInputFull(sampleIndex, fieldOrVolIndex, value) {
    if (fieldOrVolIndex === 'm') {
        _calcState.samples[sampleIndex].m = value;
    } else {
        _calcState.samples[sampleIndex].vols[fieldOrVolIndex] = value;
    }
    updateResultsFull();
    scheduleSave();
}

function updateResultsFull() {
    var method = _calcState.method;
    if (!method) return;

    _calcState.samples.forEach(function(s, i) {
        var r = calcSampleFull(s, method);
        var tag = document.getElementById('cs-result-' + i);
        if (tag) tag.textContent = r !== null ? r.toFixed(3) : '---';
    });

    var results = _calcState.samples.map(function(s) { return calcSampleFull(s, method); }).filter(function(r) { return r !== null; });

    var summaryEl = document.getElementById('calc-summary-area');
    if (summaryEl) {
        if (results.length >= 2) {
            var stats = calcStats(results);
            summaryEl.innerHTML = '<div class="calc-summary">' +
                '<div><div class="calc-avg-label">\u015arednia</div>' +
                '<div class="calc-convergence ' + (stats.convergent ? 'ok' : '') + '">\u0394 = ' + stats.delta.toFixed(3) + ' \u2014 ' + (stats.convergent ? 'zbie\u017cne' : 'BRAK ZBIE\u017bNO\u015aCI') + '</div>' +
                '<div style="font-size:10px;color:var(--text-dim);font-family:var(--mono);margin-top:2px;">RSD = ' + stats.rsd.toFixed(2) + '%   RSM = ' + stats.rsm.toFixed(2) + '%</div>' +
                '</div>' +
                '<div class="calc-avg-value">' + stats.mean.toFixed(3) + '</div>' +
            '</div>';
        } else if (results.length === 1) {
            summaryEl.innerHTML = '<div class="calc-summary"><div><div class="calc-avg-label">Wynik</div>' +
                '<div class="calc-convergence">Jedna pr\u00f3bka \u2014 dodaj drug\u0105</div></div>' +
                '<div class="calc-avg-value">' + results[0].toFixed(3) + '</div></div>';
        } else {
            summaryEl.innerHTML = '';
        }
    }

    var acceptBtn = document.getElementById('calc-accept-btn');
    if (acceptBtn) acceptBtn.style.display = results.length >= 1 ? 'block' : 'none';
}

function addSampleFull() {
    var nVols = _calcState.method.volumes.length;
    _calcState.samples.push({m: '', vols: new Array(nVols).fill(''), on: true});
    renderCalculatorFull();
}

function renderCalculator() {
    if (_calcState.fullMethod) { renderCalculatorFull(); return; }
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

    const calcFn = _calcState.fullMethod ? calcSampleFull : calcSample;
    const results = _calcState.samples
        .map(s => calcFn(s, method))
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
window.openCalculatorFull = openCalculatorFull;
window.openCalc = openCalc;
window.recalc = recalc;
window.acceptCalc = acceptCalc;
window.addSample = addSample;
window.addSampleFull = addSampleFull;
window.onSampleInput = onSampleInput;
window.onSampleInputFull = onSampleInputFull;
window.updateResultsFull = updateResultsFull;

} // end guard: CALC_METHODS already defined
