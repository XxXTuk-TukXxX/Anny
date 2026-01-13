(function(){
  function $(id){ return document.getElementById(id); }
  function toInt(v, d){ v = (v||'').trim(); var n = parseInt(v,10); return isNaN(n)? d : n; }
  function toFloat(v, d){ v = (v||'').trim(); var n = parseFloat(v); return isNaN(n)? d : n; }
  function toHexColor(val){ try { var s = String(val||'').trim().toLowerCase(); if (!s) return ''; if (s[0]==='#') return s; var map = { red:'#ff0000', green:'#008000', lime:'#00ff00', orange:'#ff9800', yellow:'#ffff00', purple:'#800080', cyan:'#00ffff', black:'#000000', white:'#ffffff', grey:'#808080', gray:'#808080' }; return map[s] || val; } catch(_) { return val; } }

  var map = {
    'width': 'note_width',
    'min-width': 'min_note_width',
    'font-size': 'note_fontsize',
    'fill': 'note_fill',
    'border': 'note_border',
    'border-width': 'note_border_width',
    'text-color': 'note_text',
    'leader-line-drawing': 'draw_leader',
    'leader-line-color': 'leader_color',
    'scan-limit': 'max_scan',
    'side': 'side',
    'center-gutter-allowance': 'allow_center_gutter',
    'center-gutter-tolerance': 'center_gutter_tolerance',
    'deduplication-scope': 'dedupe_scope',
    'column-footer-allowance': 'allow_column_footer',
    'column-footer-offset': 'column_footer_max_offset',
    'vertical-offset': 'max_vertical_offset',
    'font-file-path': 'note_fontfile',
    'api-key': 'gemini_api_key'
  };

  function populate(s){ if (!s) return; try { Object.keys(map).forEach(function(id){ var key = map[id]; var el = $(id); if (!el) return; var val = s[key]; if (val === undefined || val === null) return; if (el.type === 'checkbox') { el.checked = !!val; } else if (el.type === 'number') { el.value = String(val); } else if (el.type === 'color') { try { el.value = String(toHexColor(val)); } catch(_) {} } else { el.value = String(val); } }); } catch (e) { try { console.error(e); } catch(_){} } }
  function collect(){ var p = {}; Object.keys(map).forEach(function(id){ var key = map[id]; var el = $(id); if (!el) return; if (el.type === 'checkbox') { p[key] = !!el.checked; return; } var v = el.value; if (key === 'note_width' || key === 'min_note_width' || key === 'max_scan' || key === 'note_border_width' || key === 'column_footer_max_offset' || key === 'max_vertical_offset') { p[key] = toInt(v, 0); } else if (key === 'note_fontsize' || key === 'center_gutter_tolerance') { p[key] = toFloat(v, 0); } else { p[key] = v; } }); return p; }
  function on(el, ev, fn){ if (!el) return; if (el.addEventListener) el.addEventListener(ev, fn); else if (el.attachEvent) el.attachEvent('on'+ev, fn); }
  function bindSwatches(){ var btns = document.querySelectorAll('[data-color-for]'); for (var i=0;i<btns.length;i++){ btns[i].addEventListener('click', function(){ var id = this.getAttribute('data-color-for'); var col = this.getAttribute('data-color') || ''; var el = document.getElementById(id); if (el) { el.value = col; try { el.focus(); } catch(_){} } }); } }

  function browseFontFile(){
    var api = (window.pywebview && window.pywebview.api && window.pywebview.api.browse_font_file) ? window.pywebview.api : null;
    var input = $('font-file-path');
    var current = input ? input.value : '';
    function apply(path){ if (!path || !input) return; input.value = path; try { input.dispatchEvent(new Event('change')); } catch(_){} try { input.dispatchEvent(new Event('input')); } catch(_){} }
    if (api){
      try {
        var res = api.browse_font_file(current || '');
        if (res && typeof res.then === 'function'){
          res.then(function(val){ if (val) apply(val); }).catch(function(){});
        } else if (res){
          apply(res);
        }
        return;
      } catch (_) { /* fall through */ }
    }
    var picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = '.ttf,.otf,.ttc,.woff,.woff2';
    picker.style.display = 'none';
    async function uploadFontInBrowser(file){
      try {
        var fd = new FormData();
        fd.append('file', file);
        var res = await fetch('/api/upload_font', { method: 'POST', body: fd });
        var data = {};
        try { data = await res.json(); } catch(_) {}
        if (res.ok && data && data.ok && data.fontfile) {
          apply(String(data.fontfile));
          return true;
        }
        alert((data && data.error) ? data.error : 'Font upload failed.');
      } catch (err) {
        try { console.error(err); } catch(_) {}
        alert('Font upload failed.');
      }
      return false;
    }
    picker.addEventListener('change', async function(){
      try {
        if (picker.files && picker.files.length){
          var f = picker.files[0];
          if (f) await uploadFontInBrowser(f);
        }
      } finally {
        if (picker.parentNode){ picker.parentNode.removeChild(picker); }
      }
    });
    document.body.appendChild(picker);
    picker.click();
  }

  on($('btnCancel'), 'click', function(){ try { history.back(); } catch(_){} });
  on($('font-file-browse'), 'click', function(){ browseFontFile(); });
  on($('btnSave'), 'click', async function(){ var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; var payload = collect(); if (api && api.save_settings) { try { var res = api.save_settings(payload); if (res && typeof res.then === 'function') { res.then(function(ok){ if (ok) { alert('Settings saved'); try { history.back(); } catch(_){} } else { alert('Failed to save settings'); } }).catch(function(){ alert('Failed to save settings.'); }); } else { if (res) { alert('Settings saved'); try { history.back(); } catch(_){} } else { alert('Failed to save settings'); } } } catch (e) { alert('Failed to save settings'); } return; } try { var r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); var data = {}; try { data = await r.json(); } catch(_) {} if (r.ok && data && data.ok) { alert('Settings saved'); try { history.back(); } catch(_){} } else { alert((data && data.error) ? data.error : 'Failed to save settings'); } } catch (err) { alert('Failed to save settings.'); } });

  var debugBtn = $('btnDebugManualNote');
  var debugStatus = $('debugManualStatus');
  on(debugBtn, 'click', function(e){ if (e && e.preventDefault) e.preventDefault(); var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; if (!api || !api.debug_add_manual_note) { alert('Desktop bridge not available. Open the preview in manual mode first.'); return; } if (debugStatus) debugStatus.textContent = 'Requesting manual note…'; try { var res = api.debug_add_manual_note(); var handle = function(val){ try { var msg = val ? JSON.stringify(val) : 'No response'; if (debugStatus) debugStatus.textContent = msg; } catch(_) { if (debugStatus) debugStatus.textContent = String(val); } if (!val || !val.ok) { alert('Manual note request failed. Ensure the preview window is open and in manual mode.'); } }; if (res && typeof res.then === 'function') { res.then(handle).catch(function(err){ if (debugStatus) debugStatus.textContent = 'Error: ' + (err && err.message ? err.message : err); alert('Manual note request failed.'); }); } else { handle(res); } } catch (err) { if (debugStatus) debugStatus.textContent = 'Error: ' + (err && err.message ? err.message : err); alert('Manual note request failed.'); } });

  (async function init(){ function apiReady(){ return !!(window.pywebview && window.pywebview.api && window.pywebview.api.get_settings); } var start = Date.now(); while (!apiReady() && (Date.now() - start < 2500)) { await new Promise(r => setTimeout(r, 100)); } var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; if (api && api.get_settings) { try { var r = api.get_settings(); if (r && typeof r.then === 'function') { r.then(function(s){ populate(s); }).catch(function(){}); } else { populate(r); } } catch (e) {} try { bindSwatches(); } catch(_){} return; } try { var res = await fetch('/api/settings'); var data = await res.json(); populate(data); } catch (_) {} try { bindSwatches(); } catch(_){} })();
})();
