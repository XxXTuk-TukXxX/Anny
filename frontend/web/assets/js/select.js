(function () {
  var btn = document.getElementById('uploadBtn');
  var sbtn = document.getElementById('btnSettings');
  var fileInput = document.getElementById('fileInput');
  if (sbtn) {
    function openSettings(e){
      if (e && e.preventDefault) e.preventDefault();
      try {
        var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
        function fallback(){
          try { if (api && api.get_settings_url) { var u = api.get_settings_url(); if (u) { window.location.href = u; return; } } } catch(err){}
          try { window.location.href = '/settings.html'; return; } catch(_) {}
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
  async function uploadInBrowser(file){
    if (!file) return;
    disableBtn();
    try {
      var fd = new FormData();
      fd.append('file', file);
      var res = await fetch('/api/upload_pdf', { method: 'POST', body: fd });
      var data = {};
      try { data = await res.json(); } catch(_) {}
      if (res.ok && data && data.ok) {
        window.location.href = data.next || '/get_started.html';
        return;
      }
      alert((data && data.error) ? data.error : 'Upload failed.');
    } catch (err) {
      try { console.error(err); } catch(_) {}
      alert('Upload failed.');
    } finally {
      enableBtn();
    }
  }

  if (fileInput && fileInput.addEventListener) {
    fileInput.addEventListener('change', function(e){
      var f = (e.target && e.target.files && e.target.files[0]) ? e.target.files[0] : null;
      if (f) uploadInBrowser(f);
      try { e.target.value = ''; } catch(_) {}
    });
  }

  function start() {
    var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    if (api && api.begin_ocr) {
      disableBtn();
      try {
        var res = api.begin_ocr();
        if (res && typeof res.then === 'function') {
          res.then(function (started) { handleResult(started); })
             .catch(function () { enableBtn(); });
        } else {
          handleResult(!!res);
        }
      } catch (e) { enableBtn(); }
      return;
    }
    if (fileInput) {
      fileInput.click();
      return;
    }
    alert('File picker unavailable.');
  }
  if (btn.addEventListener) btn.addEventListener('click', start); else if (btn.attachEvent) btn.attachEvent('onclick', start);
})();
