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

  // Note: page shows progress only; no start button here.
})();
