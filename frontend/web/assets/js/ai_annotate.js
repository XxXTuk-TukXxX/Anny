(function () {
  // Settings button -> open settings page via desktop bridge
  var sbtn = document.getElementById('btnSettings');
  function openSettings(e){
    if (e && e.preventDefault) e.preventDefault();
    try {
      var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
      function fallback(){
        try { if (api && api.get_settings_url) { var u = api.get_settings_url(); if (u) { window.location.href = u; return; } } } catch(_){}
        try { window.location.href = '/settings.html'; return; } catch(_) {}
        alert('Failed to open settings.');
      }
      if (api && api.open_settings) {
        var r = api.open_settings();
        if (r && typeof r.then === 'function') { r.then(function(ok){ if (!ok) fallback(); }).catch(function(){ fallback(); }); }
        else if (!r) { fallback(); }
      } else { fallback(); }
    } catch(_){}
  }
  if (sbtn && sbtn.addEventListener) sbtn.addEventListener('click', openSettings);
  else if (sbtn && sbtn.attachEvent) sbtn.attachEvent('onclick', openSettings);

  var btn = document.getElementById('startAiBtn');
  var ta = document.getElementById('annotation-prompt');
  if (!btn) return;
  function onClick(e) {
    e.preventDefault();
    var prompt = (ta && ta.value || '').trim();
    if (!prompt) { alert('Please enter an annotation objective.'); return; }
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (api && api.start_gemini) {
      try { api.start_gemini(prompt); } catch (_) {}
      return;
    }
    btn.disabled = true;
    try {
      fetch('/api/start_gemini?async=1', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt })
      })
      .then(function(res){ return res.json().then(function(data){ return { res: res, data: data }; }); })
      .then(function(r){
        if (r.res.ok && r.data && r.data.ok) {
          window.location.href = r.data.next || '/loading_ai.html';
        } else {
          alert((r.data && r.data.error) ? r.data.error : 'Failed to start AI annotations.');
        }
      })
      .catch(function(){ alert('Failed to start AI annotations.'); })
      .finally(function(){ btn.disabled = false; });
    } catch (err) {
      btn.disabled = false;
      alert('Failed to start AI annotations.');
    }
  }
  if (btn.addEventListener) btn.addEventListener('click', onClick);
  else if (btn.attachEvent) btn.attachEvent('onclick', onClick);
})();
