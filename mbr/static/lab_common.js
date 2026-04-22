/**
 * lab_common.js — Shared utilities across all lab pages.
 * Single source of truth for validateField, product color mapping, API URLs.
 */

// ═══ PRODUCT COLOR MAPPING ═══
var PRODUCT_COLOR_RULES = [
    ['K40GLOL', 'cv-prod-glol'],
    ['K40GLO',  'cv-prod-glo'],
    ['K40GL',   'cv-prod-gl'],
    ['KK',      'cv-prod-kk'],
    ['K7',      'cv-prod-k7'],
    ['Chelamid','cv-prod-chelamid'],
    ['Cheminox','cv-prod-cheminox'],
    ['Monamid', 'cv-prod-monamid'],
    ['Alkinol', 'cv-prod-alkinol'],
    ['Alstermid','cv-prod-alkinol'],
    ['Chemal',  'cv-prod-chemal'],
    ['HSH',     'cv-prod-chemal'],
];

function getProductColorClass(prodName) {
    for (var i = 0; i < PRODUCT_COLOR_RULES.length; i++) {
        if (prodName.indexOf(PRODUCT_COLOR_RULES[i][0]) >= 0) {
            return PRODUCT_COLOR_RULES[i][1];
        }
    }
    return 'cv-prod-other';
}

// ═══ FIELD VALIDATION ═══
function validateField(input) {
    // Normalize dot to comma (Polish decimal)
    if (input.value.indexOf('.') >= 0) {
        var pos = input.selectionStart;
        input.value = input.value.replace(/\./g, ',');
        try { input.setSelectionRange(pos, pos); } catch(e) {}
    }
    var val = input.value.replace(',', '.');
    var num = parseFloat(val);
    var mn = input.dataset.min !== '' && input.dataset.min !== undefined ? parseFloat(input.dataset.min) : null;
    var mx = input.dataset.max !== '' && input.dataset.max !== undefined ? parseFloat(input.dataset.max) : null;

    input.classList.remove('ok', 'err');
    if (val && !isNaN(num)) {
        var inRange = true;
        if (mn !== null && num < mn) inRange = false;
        if (mx !== null && num > mx) inRange = false;
        input.classList.add(inRange ? 'ok' : 'err');
    }

    // Update status dot if present
    var ff = input.closest('.ff');
    if (ff) {
        var dot = ff.querySelector('.status-dot');
        if (dot) {
            dot.classList.remove('ok', 'err');
            if (val && !isNaN(num)) {
                var inR = true;
                if (mn !== null && num < mn) inR = false;
                if (mx !== null && num > mx) inR = false;
                dot.classList.add(inR ? 'ok' : 'err');
            }
        }
    }
}

// ═══ API URL BUILDER ═══
var API = {
    save: function(id) { return '/laborant/ebr/' + id + '/save'; },
    etapyAnalizy: function(id) { return '/api/ebr/' + id + '/etapy-analizy'; },
    etapyStatus: function(id) { return '/api/ebr/' + id + '/etapy-status'; },
    korekty: function(id) { return '/api/ebr/' + id + '/korekty'; },
    samples: function(id) { return '/api/ebr/' + id + '/samples'; },
    samplesGet: function(id, s, k) { return '/api/ebr/' + id + '/samples/' + s + '/' + k; },
    zatwierdz: function(id) { return '/api/ebr/' + id + '/etapy-status/zatwierdz'; },
    complete: function(id) { return '/laborant/ebr/' + id + '/complete'; },
};


// ═══ Date/time formatting — single source of truth ═══
// App timezone is Europe/Warsaw (server writes ISO strings in that zone).
// Python side uses mbr/shared/timezone.py + the pl_date Jinja filter; this JS
// helper mirrors them so dziennik, audit history, and feedback lists all
// display the same format: DD.MM HH:MM (short) or DD.MM.YYYY HH:MM (long).
function fmtDt(iso, opts) {
    if (!iso) return '';
    // Strip any timezone suffix — all stored timestamps are already Europe/Warsaw.
    var s = String(iso).replace(/([+-]\d{2}:\d{2}|Z)$/, '');
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
    if (!m) return s.slice(0, 16).replace('T', ' ');
    var yyyy = m[1], MM = m[2], dd = m[3], HH = m[4], mm = m[5];
    var long = opts && opts.long;
    return long ? (dd + '.' + MM + '.' + yyyy + ' ' + HH + ':' + mm)
                : (dd + '.' + MM + ' ' + HH + ':' + mm);
}
window.fmtDt = fmtDt;


// ═══ Rich-text markup for parameter labels ═══
// Convert ^{sup} / _{sub} markup to HTML — mirrors _rtHtml in
// admin/wzory_cert.html and _md_to_richtext in mbr/certs/generator.py.
// Same markup syntax across editor, certificate, and laborant views.
function rtHtml(text) {
    if (!text) return '';
    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    var out = '', re = /(\^\{[^}]*\}|_\{[^}]*\})/g, last = 0, m;
    while ((m = re.exec(text)) !== null) {
        if (m.index > last) out += esc(text.slice(last, m.index));
        var inner = m[0].slice(2, -1);
        out += (m[0][0] === '^') ? '<sup>' + esc(inner) + '</sup>' : '<sub>' + esc(inner) + '</sub>';
        last = re.lastIndex;
    }
    if (last < text.length) out += esc(text.slice(last));
    return out;
}
