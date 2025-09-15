(function () {
  function on(el, ev, fn) { if (!el) return; if (el.addEventListener) el.addEventListener(ev, fn); else if (el.attachEvent) el.attachEvent('on'+ev, fn); }
  var ai = document.getElementById('chooseAI');
  var js = document.getElementById('chooseJSON');
  on(ai, 'click', function (e) {
    e.preventDefault();
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (!api || !api.goto_ai_prompt) { alert('Desktop bridge not available.'); return; }
    try { api.goto_ai_prompt(); } catch (err) {}
  });
  on(js, 'click', function (e) {
    e.preventDefault();
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (!api || !api.choose_annotations_json) { alert('Desktop bridge not available.'); return; }
    try { api.choose_annotations_json(); } catch (err) {}
  });

  // Settings button -> open settings page via desktop bridge
  var sbtn = document.getElementById('btnSettings');
  function openSettings(e){
    if (e && e.preventDefault) e.preventDefault();
    try {
      var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
      function fallback(){
        try { if (api && api.get_settings_url) { var u = api.get_settings_url(); if (u) { window.location.href = u; return; } } } catch(err){}
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

