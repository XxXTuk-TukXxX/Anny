(function () {
  var COOKIE = 'anny_beta_notice_v1';
  var MAX_AGE = 60 * 60 * 24 * 365; // 1 year
  var modal = document.getElementById('betaNoticeModal');
  if (!modal) return;

  function getCookie(name) {
    try {
      var parts = String(document.cookie || '').split(';');
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i].trim();
        if (!p) continue;
        var eq = p.indexOf('=');
        var k = (eq >= 0 ? p.slice(0, eq) : p).trim();
        if (k === name) return (eq >= 0 ? p.slice(eq + 1) : '').trim();
      }
    } catch (_) {}
    return '';
  }

  function setCookie(name, value, maxAgeSeconds) {
    try {
      var secure = '';
      try {
        if (window.location && window.location.protocol === 'https:') secure = '; Secure';
      } catch (_) {}
      document.cookie =
        name +
        '=' +
        String(value || '') +
        '; Max-Age=' +
        String(maxAgeSeconds || MAX_AGE) +
        '; Path=/' +
        '; SameSite=Lax' +
        secure;
      return true;
    } catch (_) {
      return false;
    }
  }

  var closeBtn = document.getElementById('betaNoticeClose');
  var acceptBtn = document.getElementById('betaNoticeAccept');
  var startBtn = document.getElementById('betaNoticeStartTour');
  var dontShow = document.getElementById('betaNoticeDontShow');

  function show() {
    try {
      modal.style.display = 'flex';
      modal.setAttribute('aria-hidden', 'false');
      var focusTarget = acceptBtn || closeBtn;
      try { focusTarget && focusTarget.focus && focusTarget.focus(); } catch (_) {}
    } catch (_) {}
  }

  function hide(setAck) {
    try {
      if (setAck && dontShow && dontShow.checked) {
        setCookie(COOKIE, '1', MAX_AGE);
      }
    } catch (_) {}
    try {
      modal.style.display = 'none';
      modal.setAttribute('aria-hidden', 'true');
    } catch (_) {}
  }

  function onCloseRequested(setAck) {
    hide(!!setAck);
  }

  // Show once per browser (cookie-based)
  if (getCookie(COOKIE) !== '1') {
    show();
  } else {
    hide(false);
  }

  if (acceptBtn && acceptBtn.addEventListener) {
    acceptBtn.addEventListener('click', function (e) {
      try { if (e && e.preventDefault) e.preventDefault(); } catch (_) {}
      onCloseRequested(true);
    });
  }
  if (startBtn && startBtn.addEventListener) {
    startBtn.addEventListener('click', function (e) {
      try { if (e && e.preventDefault) e.preventDefault(); } catch (_) {}
      onCloseRequested(true);
      try {
        if (window.annyTour && window.annyTour.start) {
          window.annyTour.start();
        }
      } catch (_) {}
    });
  }
  if (closeBtn && closeBtn.addEventListener) {
    closeBtn.addEventListener('click', function (e) {
      try { if (e && e.preventDefault) e.preventDefault(); } catch (_) {}
      onCloseRequested(true);
    });
  }
  if (modal && modal.addEventListener) {
    modal.addEventListener('click', function (e) {
      try {
        if (e && e.target === modal) onCloseRequested(true);
      } catch (_) {}
    });
  }
  if (document && document.addEventListener) {
    document.addEventListener('keydown', function (e) {
      try {
        if (!e) return;
        if (e.key === 'Escape' && modal && modal.style && modal.style.display !== 'none') {
          onCloseRequested(true);
        }
      } catch (_) {}
    });
  }
})();
