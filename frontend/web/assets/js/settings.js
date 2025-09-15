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
    'font-name': 'note_fontname',
    'font-file-path': 'note_fontfile',
    'api-key': 'gemini_api_key'
  };

  function populate(s){ if (!s) return; try { Object.keys(map).forEach(function(id){ var key = map[id]; var el = $(id); if (!el) return; var val = s[key]; if (val === undefined || val === null) return; if (el.type === 'checkbox') { el.checked = !!val; } else if (el.type === 'number') { el.value = String(val); } else if (el.type === 'color') { try { el.value = String(toHexColor(val)); } catch(_) {} } else { el.value = String(val); } }); } catch (e) { try { console.error(e); } catch(_){} } }
  function collect(){ var p = {}; Object.keys(map).forEach(function(id){ var key = map[id]; var el = $(id); if (!el) return; if (el.type === 'checkbox') { p[key] = !!el.checked; return; } var v = el.value; if (key === 'note_width' || key === 'min_note_width' || key === 'max_scan' || key === 'note_border_width' || key === 'column_footer_max_offset' || key === 'max_vertical_offset') { p[key] = toInt(v, 0); } else if (key === 'note_fontsize' || key === 'center_gutter_tolerance') { p[key] = toFloat(v, 0); } else { p[key] = v; } }); return p; }
  function on(el, ev, fn){ if (!el) return; if (el.addEventListener) el.addEventListener(ev, fn); else if (el.attachEvent) el.attachEvent('on'+ev, fn); }
  function bindSwatches(){ var btns = document.querySelectorAll('[data-color-for]'); for (var i=0;i<btns.length;i++){ btns[i].addEventListener('click', function(){ var id = this.getAttribute('data-color-for'); var col = this.getAttribute('data-color') || ''; var el = document.getElementById(id); if (el) { el.value = col; try { el.focus(); } catch(_){} } }); } }

  on($('btnCancel'), 'click', function(){ try { history.back(); } catch(_){} });
  on($('btnSave'), 'click', function(){ var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; var payload = collect(); if (!api || !api.save_settings) { alert('Desktop bridge not available.'); return; } try { var res = api.save_settings(payload); if (res && typeof res.then === 'function') { res.then(function(ok){ if (ok) { alert('Settings saved'); try { history.back(); } catch(_){} } else { alert('Failed to save settings'); } }).catch(function(){ alert('Failed to save settings.'); }); } else { if (res) { alert('Settings saved'); try { history.back(); } catch(_){} } else { alert('Failed to save settings'); } } } catch (e) { alert('Failed to save settings'); } });

  (async function init(){ function apiReady(){ return !!(window.pywebview && window.pywebview.api && window.pywebview.api.get_settings); } var start = Date.now(); while (!apiReady() && (Date.now() - start < 2500)) { await new Promise(r => setTimeout(r, 100)); } var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null; if (!api || !api.get_settings) { return; } try { var r = api.get_settings(); if (r && typeof r.then === 'function') { r.then(function(s){ populate(s); }).catch(function(){}); } else { populate(r); } } catch (e) {} try { bindSwatches(); } catch(_){} })();
})();
