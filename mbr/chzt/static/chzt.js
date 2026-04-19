// ChZT Ścieków — modal logic with per-row autosave (on blur).
// Pattern: DB is SSOT. No localStorage. Modal opens → GET session → render.
// Each field blur → PUT /api/chzt/pomiar/<id> with the whole row.

(function(){
  'use strict';

  var _session = null;           // {id, data, n_kontenery, finalized_at, finalized_by, punkty: [...]}
  var _saveInFlight = {};        // pomiar_id → bool
  var _dirtyRows = {};           // pomiar_id → true if edited but not yet saved

  function el(id) { return document.getElementById(id); }

  function fmtTime(isoDt) {
    if (!isoDt) return '';
    var d = new Date(isoDt);
    return d.toLocaleTimeString('pl-PL', {hour:'2-digit', minute:'2-digit'});
  }

  function setStatus(kind, text) {
    var pill = el('chzt-status-pill');
    pill.className = 'chzt-meta-item chzt-status-pill ' + kind;
    var dot = pill.querySelector('.chzt-dot');
    var label = pill.querySelector('.chzt-status-text');
    if (label) label.textContent = text;
  }

  function initialStatus() {
    if (!_session) return;
    var anyFilled = _session.punkty.some(function(p) {
      return p.ph !== null || p.p1 !== null || p.p2 !== null ||
             p.p3 !== null || p.p4 !== null || p.p5 !== null;
    });
    if (_session.finalized_at) {
      setStatus('saved', '✓ zapisano');
    } else if (!anyFilled) {
      setStatus('', '⚪ nowa sesja');
    } else {
      var maxUpdated = _session.punkty
        .map(function(p){ return p.updated_at; })
        .filter(Boolean)
        .sort()
        .slice(-1)[0];
      setStatus('saved', 'zapisano · ' + fmtTime(maxUpdated));
    }
  }

  function renderFinalizedBanner() {
    var banner = el('chzt-finalize-banner');
    var footerInfo = el('chzt-finalized-info');
    var saveBtn = el('chzt-save-btn');
    if (_session.finalized_at) {
      var who = _session.finalized_by_name || ('id=' + _session.finalized_by);
      banner.textContent = '✓ Ukończono ' + fmtTime(_session.finalized_at) + ' przez ' + who;
      banner.style.display = 'block';
      saveBtn.style.display = 'none';
      footerInfo.textContent = 'Dzień ukończony — nowa sesja rozpocznie się jutro';
      footerInfo.style.display = 'inline';
      var autosaveNote = document.querySelector('.chzt-autosave-note');
      if (autosaveNote) autosaveNote.style.display = 'none';
    } else {
      banner.style.display = 'none';
      saveBtn.style.display = '';
      footerInfo.style.display = 'none';
      var autosaveNote = document.querySelector('.chzt-autosave-note');
      if (autosaveNote) autosaveNote.style.display = '';
    }
  }

  function renderDate() {
    if (!_session) return;
    var iso = _session.dt_start || '';
    var parts = iso.split('T');
    var dateParts = (parts[0] || '').split('-');
    var timeParts = (parts[1] || '').split(':');
    var formatted = (dateParts[2] || '—') + '.' + (dateParts[1] || '—') + '.' + (dateParts[0] || '—');
    if (timeParts.length >= 2) {
      formatted += ' ' + timeParts[0] + ':' + timeParts[1];
    }
    el('chzt-date').textContent = formatted;
  }

  function renderTable() {
    var html = '<table class="chzt-table">' +
      '<thead><tr><th>Punkt</th><th>pH</th><th>P1</th><th>P2</th><th>P3</th><th>P4</th><th>P5</th><th>\u015arednia</th></tr></thead><tbody>';
    _session.punkty.forEach(function(p) {
      var inv = (p.ph === null) || countNonNull(p) < 2;
      html += '<tr data-pid="' + p.id + '"' + (inv ? ' class="invalid"' : '') + '>' +
        '<td>' + escapeHtml(p.punkt_nazwa) + '</td>' +
        inputCell(p, 'ph', 'chzt-ph') +
        inputCell(p, 'p1') + inputCell(p, 'p2') + inputCell(p, 'p3') +
        inputCell(p, 'p4') + inputCell(p, 'p5') +
        '<td><span class="chzt-avg" id="chzt-avg-' + p.id + '">' + fmtAvg(p.srednia) + '</span></td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    el('chzt-body').innerHTML = html;
    _session.punkty.forEach(function(p) {
      var avgEl = el('chzt-avg-' + p.id);
      if (avgEl) styleAvgCell(avgEl, p.srednia);
    });
    wireEnterNavigation();
  }

  function countNonNull(p) {
    return ['p1','p2','p3','p4','p5'].filter(function(k){ return p[k] !== null; }).length;
  }

  function inputCell(p, field, extraCls, disabled) {
    var val = p[field] === null || p[field] === undefined ? '' : p[field];
    var cls = 'chzt-inp' + (extraCls ? ' ' + extraCls : '');
    var disabledAttr = disabled ? ' disabled' : '';
    return '<td><input class="' + cls + '" type="text" inputmode="decimal" ' +
      'pattern="[0-9]*[.,]?[0-9]*" ' +
      'data-pid="' + p.id + '" data-field="' + field + '" ' +
      'value="' + val + '"' + disabledAttr + '></td>';
  }

  function fmtAvg(v) {
    if (v === null || v === undefined) return '\u2014';
    return Math.round(v).toLocaleString('pl-PL');
  }

  function styleAvgCell(el, v) {
    if (v !== null && v !== undefined && v > 40000) {
      el.style.color = 'var(--amber, #b45309)';
      el.parentElement && el.parentElement.parentElement && el.parentElement.parentElement.classList.add('row-warn');
    } else {
      el.style.color = '';
      el.parentElement && el.parentElement.parentElement && el.parentElement.parentElement.classList.remove('row-warn');
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function parseNum(s) {
    if (s === '' || s === null || s === undefined) return null;
    var n = parseFloat(String(s).replace(',', '.'));
    return isNaN(n) ? null : n;
  }

  function getRowValues(pid) {
    var out = {};
    document.querySelectorAll('input[data-pid="' + pid + '"]').forEach(function(inp) {
      if (inp.disabled) return;
      var field = inp.dataset.field;
      if (!field) return;
      out[field] = parseNum(inp.value);
    });
    return out;
  }

  function wireInputHandlers(rootSelector) {
    var sel = (rootSelector || '#chzt-body') + ' .chzt-inp';
    document.querySelectorAll(sel).forEach(function(inp) {
      if (inp.dataset.wired === '1') return;
      inp.dataset.wired = '1';
      inp.addEventListener('input', function(){
        // regex validation only — no save
        if (inp.value !== '' && !/^[0-9]*[.,]?[0-9]*$/.test(inp.value)) {
          inp.classList.add('invalid');
        } else {
          inp.classList.remove('invalid');
        }
        _markDirty(parseInt(inp.dataset.pid));
      });
      inp.addEventListener('blur', function(){
        var pid = parseInt(inp.dataset.pid);
        if (_dirtyRows[pid]) {
          saveRow(pid, 0);
          _dirtyRows[pid] = false;
        }
      });
    });
  }

  function _markDirty(pid) {
    _dirtyRows[pid] = true;
  }

  function flushDirtyRows() {
    Object.keys(_dirtyRows).forEach(function(pidStr){
      if (_dirtyRows[pidStr]) {
        saveRow(parseInt(pidStr), 0);
        _dirtyRows[pidStr] = false;
      }
    });
  }

  function _canEditExt(rola) {
    return ['produkcja', 'admin', 'technolog'].indexOf(rola) >= 0;
  }

  function _canEditInternal(rola) {
    return ['lab', 'kj', 'cert', 'admin', 'technolog'].indexOf(rola) >= 0;
  }

  function _renderExtSection(rola) {
    if (!_session) return;
    var szambiarka = _session.punkty.find(function(p){ return p.punkt_nazwa === 'szambiarka'; });
    if (!szambiarka) return;

    var canEdit = _canEditExt(rola);
    var detailView = el('chzt-detail-view');
    if (!detailView) return;

    var section = document.createElement('div');
    section.id = 'chzt-ext-section';
    section.className = 'chzt-ext-section';

    var fmt = function(v) { return v === null || v === undefined ? '' : v; };
    var roCls = canEdit ? '' : 'readonly';
    var disabledAttr = canEdit ? '' : 'disabled';

    section.innerHTML =
      '<div class="chzt-ext-title">Analiza zewnętrzna \u2014 Szambiarka</div>' +
      '<div class="chzt-ext-grid">' +
        '<div class="chzt-ext-field">' +
          '<label>pH zewnętrzne</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="ext_ph" value="' + fmt(szambiarka.ext_ph) + '" ' +
                 disabledAttr + '>' +
        '</div>' +
        '<div class="chzt-ext-field">' +
          '<label>ChZT zewnętrzne</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="ext_chzt" value="' + fmt(szambiarka.ext_chzt) + '" ' +
                 disabledAttr + '>' +
          '<span class="chzt-ext-unit">mg O\u2082/l</span>' +
        '</div>' +
        '<div class="chzt-ext-field">' +
          '<label>Waga beczki</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="waga_kg" value="' + fmt(szambiarka.waga_kg) + '" ' +
                 disabledAttr + '>' +
          '<span class="chzt-ext-unit">kg</span>' +
        '</div>' +
      '</div>';

    var registryEl = detailView.querySelector('.registry');
    if (registryEl && registryEl.parentNode) {
      registryEl.parentNode.insertAdjacentElement('afterend', section);
    } else {
      detailView.appendChild(section);
    }

    if (canEdit) {
      wireInputHandlers('#chzt-ext-section');
    }
  }

  function saveRow(pid, attempt) {
    if (_saveInFlight[pid]) {
      setTimeout(function(){ saveRow(pid, 0); }, 400);
      return;
    }
    _saveInFlight[pid] = true;
    _pushStatus('saving', '🟡 zapisywanie…');
    var values = getRowValues(pid);
    fetch('/api/chzt/pomiar/' + pid, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(values),
    }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _saveInFlight[pid] = false;
      if (_session) {
        for (var i = 0; i < _session.punkty.length; i++) {
          if (_session.punkty[i].id === pid) {
            _session.punkty[i] = Object.assign(_session.punkty[i], resp.pomiar);
            break;
          }
        }
      }
      var avgEl = el('chzt-avg-' + pid);
      if (avgEl) {
        avgEl.textContent = fmtAvg(resp.pomiar.srednia);
        styleAvgCell(avgEl, resp.pomiar.srednia);
      }
      _pushStatus('saved', 'zapisano · ' + fmtTime(resp.pomiar.updated_at));
    }).catch(function(err){
      _saveInFlight[pid] = false;
      if (attempt < 3) {
        setTimeout(function(){ saveRow(pid, attempt + 1); }, 1000);
      } else {
        _pushStatus('error', '🔴 błąd połączenia');
      }
    });
  }

  // _pushStatus writes status into whatever indicator is active:
  // the modal status-pill if modal is visible, else the expand status badge.
  function _pushStatus(kind, text) {
    var overlay = el('chzt-overlay');
    if (overlay && overlay.classList.contains('show')) {
      setStatus(kind, text);
      return;
    }
    var badges = document.querySelectorAll('.chzt-expand-status');
    badges.forEach(function(b){
      b.className = 'chzt-expand-status ' + kind;
      b.textContent = text;
    });
  }

  function wireEnterNavigation() {
    var inputs = Array.prototype.slice.call(document.querySelectorAll('#chzt-body .chzt-inp'));
    inputs.forEach(function(inp, idx) {
      inp.addEventListener('keydown', function(ev){
        if (ev.key !== 'Enter') return;
        ev.preventDefault();
        var next = inputs[idx + 1];
        if (next) {
          next.focus();
          next.select();
        } else {
          var btn = el('chzt-save-btn');
          if (btn && btn.style.display !== 'none') btn.focus();
        }
      });
    });
    wireInputHandlers();
  }

  function loadSession(urlSuffix) {
    // urlSuffix can be numeric id or (legacy) data string — routes now expect int id
    setStatus('saving', '🟡 ładowanie…');
    fetch('/api/chzt/session/' + urlSuffix, {
      headers: {'Accept': 'application/json'},
    }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      el('chzt-n-kontenery').value = _session.n_kontenery;
      el('chzt-meta-punkty').textContent = _session.punkty.length + ' punktów';
      el('chzt-meta-kontenery').textContent = _session.n_kontenery + ' kontenerów';
      renderDate();
      renderTable();
      renderFinalizedBanner();
      initialStatus();
    }).catch(function(){
      setStatus('error', '🔴 nie udało się wczytać');
    });
  }

  window.openChztModal = function(arg) {
    el('chzt-overlay').classList.add('show');
    if (el('chzt-errors')) el('chzt-errors').style.display = 'none';
    if (el('chzt-toolbar-error')) el('chzt-toolbar-error').textContent = '';
    if (el('chzt-create-error')) el('chzt-create-error').textContent = '';
    if (typeof arg === 'number' || (typeof arg === 'string' && /^\d+$/.test(arg))) {
      // Numeric id — load specific session (e.g. from historia Edit)
      _showEditPane();
      loadSession(arg);
    } else {
      // From narzedzia card: try active session, else show create pane
      loadActiveOrCreate();
    }
  };

  function _showCreatePane() {
    if (el('chzt-create-pane')) el('chzt-create-pane').style.display = '';
    if (el('chzt-edit-pane')) el('chzt-edit-pane').style.display = 'none';
  }

  function _showEditPane() {
    if (el('chzt-create-pane')) el('chzt-create-pane').style.display = 'none';
    if (el('chzt-edit-pane')) el('chzt-edit-pane').style.display = '';
  }

  function loadActiveOrCreate() {
    fetch('/api/chzt/session/active', {headers: {'Accept': 'application/json'}})
      .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(resp){
        if (resp.session === null) {
          _showCreatePane();
          var inp = el('chzt-create-n');
          if (inp) {
            inp.value = 8;
            setTimeout(function(){ inp.focus(); inp.select(); }, 50);
          }
        } else {
          _showEditPane();
          _session = resp.session;
          el('chzt-n-kontenery').value = _session.n_kontenery;
          el('chzt-meta-punkty').textContent = _session.punkty.length + ' punktów';
          el('chzt-meta-kontenery').textContent = _session.n_kontenery + ' kontenerów';
          renderDate();
          renderTable();
          renderFinalizedBanner();
          initialStatus();
        }
      })
      .catch(function(){
        _showEditPane();
        setStatus('error', '🔴 nie udało się wczytać');
      });
  }

  window.chztSubmitNew = function() {
    var input = el('chzt-create-n');
    var n = parseInt(input.value);
    var errBox = el('chzt-create-error');
    if (isNaN(n) || n < 0 || n > 20) {
      errBox.textContent = 'Oczekuję liczby 0–20';
      return;
    }
    errBox.textContent = '';
    var btn = el('chzt-create-submit');
    btn.disabled = true;
    btn.textContent = 'Tworzenie…';

    fetch('/api/chzt/session/new', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({n_kontenery: n}),
    }).then(function(r){
      if (r.status === 409) {
        return r.json().then(function(b){
          errBox.textContent = b.error || 'Istnieje otwarta sesja';
          throw new Error('conflict');
        });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      _showEditPane();
      el('chzt-n-kontenery').value = _session.n_kontenery;
      el('chzt-meta-punkty').textContent = _session.punkty.length + ' punktów';
      el('chzt-meta-kontenery').textContent = _session.n_kontenery + ' kontenerów';
      renderDate();
      renderTable();
      renderFinalizedBanner();
      initialStatus();
      btn.disabled = false;
      btn.textContent = 'Rozpocznij sesję';
    }).catch(function(){
      btn.disabled = false;
      btn.textContent = 'Rozpocznij sesję';
    });
  };

  window.closeChztModal = function() {
    flushDirtyRows();
    el('chzt-overlay').classList.remove('show');
  };

  window.addEventListener('beforeunload', function(){
    flushDirtyRows();
  });

  window.chztApplyKontenery = function() {
    if (!_session) return;
    var v = parseInt(el('chzt-n-kontenery').value);
    if (isNaN(v) || v < 0 || v > 20) {
      el('chzt-toolbar-error').textContent = 'Oczekuję liczby 0–20';
      return;
    }
    el('chzt-toolbar-error').textContent = '';
    fetch('/api/chzt/session/' + _session.id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({n_kontenery: v}),
    }).then(function(r){
      if (r.status === 409) {
        return r.json().then(function(b){
          el('chzt-toolbar-error').textContent = b.error || 'Kontenery z danymi — wyczyść najpierw.';
          throw new Error('conflict');
        });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      renderTable();
      initialStatus();
    }).catch(function(){});
  };

  window.chztFinalize = function() {
    if (!_session) return;
    flushDirtyRows();
    var localErrors = [];
    _session.punkty.forEach(function(p) {
      var row = getRowValues(p.id);
      if (row.ph === null) {
        localErrors.push({punkt_nazwa: p.punkt_nazwa, reason: 'brak pH'});
      } else {
        var nonnull = ['p1','p2','p3','p4','p5'].filter(function(k){ return row[k] !== null; }).length;
        if (nonnull < 2) {
          localErrors.push({punkt_nazwa: p.punkt_nazwa, reason: 'min. 2 pomiary'});
        }
      }
    });
    var errBox = el('chzt-errors');
    if (localErrors.length > 0) {
      errBox.innerHTML = '<b>Nie można sfinalizować:</b><br>' +
        localErrors.map(function(e){ return '• ' + e.punkt_nazwa + ' — ' + e.reason; }).join('<br>');
      errBox.style.display = 'block';
      highlightInvalid(localErrors);
      return;
    }
    errBox.style.display = 'none';
    var btn = el('chzt-save-btn');
    btn.disabled = true;
    btn.textContent = 'Finalizowanie…';
    fetch('/api/chzt/session/' + _session.id + '/finalize', {method: 'POST'})
      .then(function(r){
        if (r.status === 400) {
          return r.json().then(function(b){
            errBox.innerHTML = '<b>Walidacja serwera:</b><br>' +
              (b.errors || []).map(function(e){ return '• ' + e.punkt_nazwa + ' — ' + e.reason; }).join('<br>');
            errBox.style.display = 'block';
            throw new Error('validation');
          });
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(resp){
        _session = resp.session;
        renderFinalizedBanner();
        initialStatus();
        btn.textContent = 'Zakończ sesję';
        btn.disabled = false;
      })
      .catch(function(){
        btn.textContent = 'Zakończ sesję';
        btn.disabled = false;
      });
  };

  function highlightInvalid(errors) {
    var byName = {};
    errors.forEach(function(e){ byName[e.punkt_nazwa] = e.reason; });
    document.querySelectorAll('#chzt-body tbody tr').forEach(function(tr){
      var pid = parseInt(tr.dataset.pid);
      var p = _session.punkty.find(function(x){ return x.id === pid; });
      if (p && byName[p.punkt_nazwa]) {
        tr.classList.add('invalid');
      } else {
        tr.classList.remove('invalid');
      }
    });
  }
  function fetchJson(url) {
    return fetch(url, {headers: {'Accept': 'application/json'}})
      .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  // ══════ Historia — list ↔ detail view swap (jak w Rejestrze ukończonych) ══════

  window.chztShowDetail = function(sid, dtStart) {
    flushDirtyRows();

    var listView = el('chzt-list-view');
    var detailView = el('chzt-detail-view');
    var tbody = el('chzt-detail-tbody');
    var badge = el('chzt-detail-badge');
    var dateEl = el('chzt-detail-date');
    var statusEl = el('chzt-detail-status');
    if (!listView || !detailView || !tbody) return;

    listView.style.display = 'none';
    detailView.style.display = '';
    tbody.innerHTML = '<tr><td colspan="8" class="chzt-card-loading">wczytywanie\u2026</td></tr>';
    if (badge) badge.innerHTML = '';
    if (statusEl) { statusEl.className = 'chzt-expand-status'; statusEl.textContent = ''; }

    // Remove any prior ext section
    var prevExt = document.getElementById('chzt-ext-section');
    if (prevExt) prevExt.remove();

    // Format date for header (from dtStart string)
    if (dateEl && dtStart) {
      var p = (dtStart || '').split('T');
      var d = (p[0] || '').split('-');
      var t = (p[1] || '').split(':');
      var fmt = (d[2] || '\u2014') + '.' + (d[1] || '\u2014') + '.' + (d[0] || '\u2014');
      if (t.length >= 2) fmt += ' ' + t[0] + ':' + t[1];
      dateEl.textContent = fmt;
    }

    fetchJson('/api/chzt/session/' + sid).then(function(resp){
      _session = resp.session;
      var rola = window._chztUserRola || 'lab';

      if (badge) {
        if (_session.finalized_at) {
          var who = _session.finalized_by_name || '\u2014';
          badge.innerHTML = '<span class="chzt-expand-finalized">\u2713 Uko\u0144czono ' +
            fmtTime(_session.finalized_at) + ' \u00b7 ' + escapeHtmlHist(who) + '</span>';
        } else {
          badge.innerHTML = '<span class="chzt-expand-draft">\u25cf Otwarta</span>';
        }
      }

      // Main pomiary table
      var canEditInt = _canEditInternal(rola);
      var rows = '';
      _session.punkty.forEach(function(p) {
        var warn = p.srednia !== null && p.srednia > 40000;
        rows += '<tr data-pid="' + p.id + '"' + (warn ? ' class="row-warn"' : '') + '>' +
          '<td>' + escapeHtmlHist(p.punkt_nazwa) + '</td>' +
          inputCell(p, 'ph', canEditInt ? 'chzt-ph' : 'chzt-ph readonly', !canEditInt) +
          inputCell(p, 'p1', canEditInt ? '' : 'readonly', !canEditInt) +
          inputCell(p, 'p2', canEditInt ? '' : 'readonly', !canEditInt) +
          inputCell(p, 'p3', canEditInt ? '' : 'readonly', !canEditInt) +
          inputCell(p, 'p4', canEditInt ? '' : 'readonly', !canEditInt) +
          inputCell(p, 'p5', canEditInt ? '' : 'readonly', !canEditInt) +
          '<td><span class="srednia-val' + (warn ? ' warn' : '') + '" id="chzt-avg-' + p.id + '">' +
            (p.srednia === null ? '\u2014' : Math.round(p.srednia).toLocaleString('pl-PL')) +
          '</span></td>' +
          '</tr>';
      });
      tbody.innerHTML = rows;

      if (canEditInt) {
        wireInputHandlers('#chzt-detail-tbody');
      }

      _session.punkty.forEach(function(p) {
        var avgEl = el('chzt-avg-' + p.id);
        if (avgEl) styleAvgCell(avgEl, p.srednia);
      });

      // Render bottom ext section (szambiarka)
      _renderExtSection(rola);
    }).catch(function(){
      tbody.innerHTML = '<tr><td colspan="8" class="chzt-card-loading">b\u0142\u0105d wczytywania</td></tr>';
    });
  };

  window.chztShowList = function() {
    flushDirtyRows();
    _session = null;
    var listView = el('chzt-list-view');
    var detailView = el('chzt-detail-view');
    if (listView && detailView) {
      detailView.style.display = 'none';
      listView.style.display = '';
    }
  };

  function readCell(v) {
    return '<td>' + (v === null || v === undefined ? '—' : String(v).replace('.', ',')) + '</td>';
  }

  function escapeHtmlHist(s) {
    return String(s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

})();
