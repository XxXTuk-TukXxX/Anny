(function () {
  var btn = document.getElementById('uploadBtn');
  var sbtn = document.getElementById('btnSettings');
  if (sbtn) {
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
    if (sbtn.addEventListener) sbtn.addEventListener('click', openSettings); else if (sbtn.attachEvent) sbtn.attachEvent('onclick', openSettings);
  }

  if (!btn) return;

  function enableBtn() {
    btn.disabled = false;
    try { btn.classList.remove('opacity-75'); } catch (e) {}
  }
  function disableBtn() {
    btn.disabled = true;
    try { btn.classList.add('opacity-75'); } catch (e) {}
  }
  function handleResult(started) {
    if (!started) enableBtn();
  }
  function start() {
    disableBtn();
    try {
      var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
      if (api && api.begin_ocr) {
        var res = api.begin_ocr();
        if (res && typeof res.then === 'function') {
          res.then(function (started) { handleResult(started); })
             .catch(function () { enableBtn(); });
        } else {
          handleResult(!!res);
        }
      } else {
        alert('Desktop bridge not available. Please launch via the desktop app.');
        enableBtn();
      }
    } catch (e) { enableBtn(); }
  }
  if (btn.addEventListener) btn.addEventListener('click', start); else if (btn.attachEvent) btn.attachEvent('onclick', start);
})();

