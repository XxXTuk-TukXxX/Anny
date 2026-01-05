(function () {
  function on(el, ev, fn) { if (!el) return; if (el.addEventListener) el.addEventListener(ev, fn); else if (el.attachEvent) el.attachEvent('on'+ev, fn); }
  var ai = document.getElementById('chooseAI');
  var js = document.getElementById('chooseJSON');
  var manual = document.getElementById('chooseManual');
  var jsonInput = document.getElementById('jsonInput');

  async function uploadAnnotations(file){
    if (!file) return;
    try {
      var fd = new FormData();
      fd.append('file', file);
      var res = await fetch('/api/upload_annotations', { method: 'POST', body: fd });
      var data = {};
      try { data = await res.json(); } catch(_) {}
      if (res.ok && data && data.ok) {
        window.location.href = data.next || '/preview.html';
        return;
      }
      alert((data && data.error) ? data.error : 'Upload failed.');
    } catch (err) {
      alert('Upload failed.');
    }
  }

  if (jsonInput && jsonInput.addEventListener) {
    jsonInput.addEventListener('change', function(e){
      var f = (e.target && e.target.files && e.target.files[0]) ? e.target.files[0] : null;
      if (f) uploadAnnotations(f);
      try { e.target.value = ''; } catch(_) {}
    });
  }

  on(ai, 'click', function (e) {
    e.preventDefault();
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (api && api.goto_ai_prompt) {
      try { api.goto_ai_prompt(); } catch (err) {}
      return;
    }
    window.location.href = '/AI/annotate_with_ai.html';
  });
  on(js, 'click', function (e) {
    e.preventDefault();
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (api && api.choose_annotations_json) {
      try { api.choose_annotations_json(); } catch (err) {}
      return;
    }
    if (jsonInput) { jsonInput.click(); return; }
    alert('Desktop bridge not available.');
  });
  on(manual, 'click', function (e) {
    e.preventDefault();
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (api && api.start_manual_mode) {
      try { api.start_manual_mode(); } catch (err) {}
      return;
    }
    try {
      fetch('/api/start_manual', { method: 'POST' })
        .then(function(res){ return res.json(); })
        .then(function(data){
          if (data && data.ok) { window.location.href = data.next || '/preview.html'; }
          else { alert((data && data.error) ? data.error : 'Failed to start manual mode.'); }
        })
        .catch(function(){ alert('Failed to start manual mode.'); });
    } catch (err) { alert('Failed to start manual mode.'); }
  });

  // Settings button -> open settings page via desktop bridge
  var sbtn = document.getElementById('btnSettings');
  function openSettings(e){
    if (e && e.preventDefault) e.preventDefault();
    try {
      var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
      function fallback(){
        try { window.location.href = '/settings.html'; return; } catch(err){}
        alert('Failed to open settings.');
      }
      if (api && api.open_settings) {
        var r = api.open_settings();
        if (r && typeof r.then === 'function') r.then(function(ok){ if (!ok) fallback(); }).catch(function(){ fallback(); });
        else if (!r) fallback();
      } else fallback();
    } catch(err){}
  }
  if (sbtn && sbtn.addEventListener) sbtn.addEventListener('click', openSettings); else if (sbtn && sbtn.attachEvent) sbtn.attachEvent('onclick', openSettings);
})();
