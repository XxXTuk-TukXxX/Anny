(function () {
  var COOKIE = 'anny_beta_notice_v1';
  var MAX_AGE = 60 * 60 * 24 * 365; // 1 year

  function ensureModal() {
    var existing = document.getElementById('betaNoticeModal');
    if (existing) return existing;
    try {
      var host = document.createElement('div');
      host.innerHTML =
        '<div id="betaNoticeModal" class="fixed inset-0 z-[3000] flex items-center justify-center bg-black/50 p-4" style="display: none;" role="dialog" aria-modal="true" aria-labelledby="betaNoticeTitle" aria-hidden="true">' +
        '  <div class="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-black/10">' +
        '    <div class="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-4">' +
        '      <div>' +
        '        <h2 id="betaNoticeTitle" class="text-xl font-bold text-gray-900">Welcome to Anny (Beta)</h2>' +
        '        <p class="mt-1 text-sm text-gray-600">A quick note before you start.</p>' +
        '      </div>' +
        '      <button id="betaNoticeClose" type="button" class="inline-flex h-9 w-9 items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900" aria-label="Close">' +
        '        <span class="material-symbols-outlined text-xl">close</span>' +
        '      </button>' +
        '    </div>' +
        '' +
        '    <div class="max-h-[70vh] space-y-4 overflow-y-auto px-6 py-5">' +
        '      <div class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">' +
        '        <p class="font-semibold">Beta notice</p>' +
        '        <ul class="mt-2 list-disc space-y-1 pl-5">' +
        '          <li>This app is in beta — you may run into bugs or unexpected errors.</li>' +
        '          <li>AI annotations are limited and can be rate-limited when many users run requests at once.</li>' +
        '        </ul>' +
        '      </div>' +
        '' +
        '      <div class="rounded-lg border border-gray-200 bg-white p-4">' +
        '        <h3 class="text-sm font-semibold text-gray-900">How to use Anny</h3>' +
        '        <ol class="mt-3 list-decimal space-y-2 pl-5 text-sm text-gray-700">' +
        '          <li><span class="font-semibold">Create your handwriting font:</span> open <a class="font-semibold text-blue-700 hover:underline" href="/custom_font_generator/font_page.html">Font maker</a>, download the template, fill it in, upload the scan/photo, preview &amp; tweak thickness/spacing, then download the generated <span class="font-mono">.ttf</span>.</li>' +
        '          <li><span class="font-semibold">Upload your font in Settings:</span> click the <span class="font-semibold">Settings</span> button (top-right) → <span class="font-semibold">Font File</span> → <span class="font-semibold">Browse…</span> → select your <span class="font-mono">.ttf</span> → <span class="font-semibold">Save</span>.</li>' +
        '          <li><span class="font-semibold">Upload your PDF:</span> click <span class="font-semibold">Upload PDF</span>. OCR runs automatically.</li>' +
        '          <li><span class="font-semibold">Generate annotations:</span> choose <span class="font-semibold">Use AI</span>, type your prompt, and wait. If the AI is busy, try again a bit later.</li>' +
        '          <li><span class="font-semibold">Review &amp; export:</span> in the preview, drag boxes to reposition, tap/click a box to edit its text, and export the final PDF.</li>' +
        '        </ol>' +
        '        <p class="mt-3 text-xs text-gray-500">Tip: If AI misses something, you can use “AI annotate page” from the preview to add more annotations to the current page.</p>' +
        '      </div>' +
        '    </div>' +
        '' +
        '    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 px-6 py-4">' +
        '      <label class="inline-flex items-center gap-2 text-sm text-gray-700">' +
        '        <input id="betaNoticeDontShow" type="checkbox" class="rounded border-gray-300" checked />' +
        '        Don’t show again' +
        '      </label>' +
        '      <div class="flex flex-wrap items-center gap-2">' +
        '        <button id="betaNoticeAccept" type="button" class="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-5 py-2 text-sm font-semibold text-gray-900 shadow-sm hover:bg-gray-50">Got it</button>' +
        '        <button id="betaNoticeStartTour" type="button" class="inline-flex items-center justify-center rounded-md bg-[var(--primary-color)] px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-opacity-90">Start tour</button>' +
        '      </div>' +
        '    </div>' +
        '  </div>' +
        '</div>';
      var node = host.firstChild;
      document.body.appendChild(node);
      return node;
    } catch (_) {
      return null;
    }
  }

  var modal = ensureModal();
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

  // Allow reopening via Help button
  (function bindHelp() {
    var helpBtn = document.getElementById('btnHelp');
    if (!helpBtn) {
      try { helpBtn = document.querySelector('button[title="Help"]'); } catch (_) {}
    }
    if (!helpBtn || !helpBtn.addEventListener) return;
    helpBtn.addEventListener('click', function (e) {
      try { if (e && e.preventDefault) e.preventDefault(); } catch (_) {}
      show();
    });
  })();

  try {
    window.annyBetaNotice = { show: show, hide: hide };
  } catch (_) {}

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
