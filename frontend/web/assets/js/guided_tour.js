(function () {
  var ACTIVE_COOKIE = 'anny_tour_active_v1';
  var STEP_COOKIE = 'anny_tour_step_v1';
  var DONE_COOKIE = 'anny_tour_done_v1';
  var MAX_AGE = 60 * 60 * 24 * 365; // 1 year

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

  function clearCookie(name) {
    try {
      setCookie(name, '', 0);
    } catch (_) {}
  }

  function normalizePath(pathname) {
    var p = String(pathname || '').trim();
    if (!p || p === '/') return '/upload.html';
    if (p === '/font-maker' || p === '/font-maker/') return '/custom_font_generator/font_page.html';
    return p;
  }

  function currentPath() {
    try {
      return normalizePath(window.location && window.location.pathname);
    } catch (_) {
      return '/upload.html';
    }
  }

  function openSidebar() {
    var sidebar = document.getElementById('workspaceSidebar');
    if (!sidebar || !sidebar.classList) return;
    try {
      sidebar.classList.remove('-translate-x-full');
      sidebar.classList.add('translate-x-0');
    } catch (_) {}
  }

  var STEPS = [
    {
      id: 'create_font',
      page: '/upload.html',
      selector: '#annyNavFontMaker',
      title: 'Create your handwriting font',
      body: 'Start here. Open Font maker to download the template and generate your .ttf handwriting font.',
      before: function () {
        openSidebar();
      },
      advanceOnClick: true,
    },
    {
      id: 'download_template',
      page: '/custom_font_generator/font_page.html',
      selector: '#annyDownloadTemplate',
      title: 'Download the template',
      body: 'Download and print the template PDF, fill it in clearly, then scan or photograph it.',
    },
    {
      id: 'upload_sheet',
      page: '/custom_font_generator/font_page.html',
      selector: '#annyChooseScan',
      title: 'Upload your filled sheet',
      body: 'Upload a PNG/JPG/PDF of your filled template.',
    },
    {
      id: 'generate_preview',
      page: '/custom_font_generator/font_page.html',
      selector: '#annyGenerateFont',
      title: 'Generate your font',
      body: 'Generate your font and open the preview. From there you can download the .ttf.',
    },
    {
      id: 'preview_download',
      page: '/font_preview.html',
      selector: '#downloadBtn',
      title: 'Download your .ttf',
      body: 'Download the generated font file. You can also tweak thickness/spacing here.',
      passive: true,
    },
    {
      id: 'open_settings',
      page: '/upload.html',
      selector: '#btnSettings',
      title: 'Open Settings',
      body: 'Next, upload your font and set your Gemini API key in Settings.',
      advanceOnClick: true,
    },
    {
      id: 'upload_font_in_settings',
      page: '/settings.html',
      selector: '#font-file-browse',
      title: 'Upload your font',
      body: 'Click Browse… and select your .ttf file.',
    },
    {
      id: 'save_settings',
      page: '/settings.html',
      selector: '#btnSave',
      title: 'Save',
      body: 'Save your settings, then go back to upload your PDF.',
    },
    {
      id: 'upload_pdf',
      page: '/upload.html',
      selector: '#uploadBtn',
      title: 'Upload a PDF',
      body: 'Upload a PDF to run OCR. After scanning you can use AI or place notes manually, then export the final PDF.',
    },
    {
      id: 'preview_tips',
      page: '/preview.html',
      selector: '#addBoxBtn',
      title: 'Preview tips',
      body: 'In the preview you can drag boxes, tap/click to edit text, add new boxes, and export the final PDF.',
      passive: true,
    },
  ];

  var NON_PASSIVE_TOTAL = (function () {
    var n = 0;
    for (var i = 0; i < STEPS.length; i++) {
      if (STEPS[i] && !STEPS[i].passive) n++;
    }
    return n || STEPS.length;
  })();

  function clampIndex(n) {
    var i = parseInt(String(n || '0'), 10);
    if (!isFinite(i) || i < 0) i = 0;
    if (i >= STEPS.length) i = STEPS.length - 1;
    return i;
  }

  function getStepIndex() {
    return clampIndex(getCookie(STEP_COOKIE) || '0');
  }

  function isActive() {
    return getCookie(ACTIVE_COOKIE) === '1';
  }

  function markActive(active) {
    if (active) {
      setCookie(ACTIVE_COOKIE, '1', MAX_AGE);
      clearCookie(DONE_COOKIE);
      try {
        if (document.documentElement && document.documentElement.classList) {
          document.documentElement.classList.add('anny-tour-active');
        }
      } catch (_) {}
      return;
    }
    clearCookie(ACTIVE_COOKIE);
    try {
      if (document.documentElement && document.documentElement.classList) {
        document.documentElement.classList.remove('anny-tour-active');
      }
    } catch (_) {}
  }

  function setStepIndex(i) {
    setCookie(STEP_COOKIE, String(clampIndex(i)), MAX_AGE);
  }

  function findBestStepForPath(path, fromIndex) {
    var p = normalizePath(path);
    var start = clampIndex(fromIndex);
    for (var i = start; i < STEPS.length; i++) {
      if (STEPS[i] && STEPS[i].page === p) return i;
    }
    for (var j = start - 1; j >= 0; j--) {
      if (STEPS[j] && STEPS[j].page === p) return j;
    }
    for (var k = 0; k < STEPS.length; k++) {
      if (STEPS[k] && STEPS[k].page === p) return k;
    }
    return -1;
  }

  var ui = {
    root: null,
    shadeTop: null,
    shadeLeft: null,
    shadeRight: null,
    shadeBottom: null,
    spotlight: null,
    tooltip: null,
    title: null,
    body: null,
    stepLabel: null,
    backBtn: null,
    nextBtn: null,
    skipBtn: null,
  };

  var state = {
    currentIndex: -1,
    target: null,
    updateTimer: null,
    retryTimer: null,
    boundAdvance: {},
    initted: false,
  };

  function ensureStyles() {
    var id = 'annyGuidedTourStyle';
    if (document.getElementById(id)) return;
    var primary = '#137fec';
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue('--primary-color');
      if (v && v.trim()) primary = v.trim();
    } catch (_) {}

    var style = document.createElement('style');
    style.id = id;
    style.textContent =
      '#annyTourRoot{position:fixed;inset:0;z-index:6000;display:none;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}' +
      '#annyTourRoot *{box-sizing:border-box;}' +
      '.anny-tour-shade{position:fixed;background:rgba(0,0,0,0.55);}' +
      '.anny-tour-spotlight{position:fixed;border:2px solid ' +
      primary +
      ';border-radius:14px;box-shadow:0 0 0 6px rgba(19,127,236,0.18);pointer-events:none;}' +
      '.anny-tour-tooltip{position:fixed;max-width:min(420px,calc(100vw - 24px));background:#fff;color:#111827;border-radius:16px;padding:14px 14px 12px;box-shadow:0 20px 50px rgba(0,0,0,0.25);border:1px solid rgba(0,0,0,0.08);}' +
      '.anny-tour-title{font-weight:800;font-size:16px;line-height:1.25;margin:0 0 6px;}' +
      '.anny-tour-body{font-size:13px;line-height:1.45;color:#374151;margin:0;}' +
      '.anny-tour-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:12px;}' +
      '.anny-tour-step{font-size:12px;color:#6b7280;}' +
      '.anny-tour-actions{display:flex;gap:8px;align-items:center;}' +
      '.anny-tour-btn{appearance:none;border:1px solid rgba(0,0,0,0.14);background:#fff;color:#111827;border-radius:10px;padding:8px 10px;font-size:12px;font-weight:700;cursor:pointer;}' +
      '.anny-tour-btn:hover{background:#f9fafb;}' +
      '.anny-tour-btn-primary{background:' +
      primary +
      ';border-color:' +
      primary +
      ';color:#fff;}' +
      '.anny-tour-btn-primary:hover{filter:brightness(0.97);}' +
      '.anny-tour-btn[disabled]{opacity:0.5;cursor:not-allowed;}' +
      '@media (prefers-color-scheme: dark){.anny-tour-tooltip{background:#0b1220;color:#e5e7eb;border-color:rgba(255,255,255,0.12);} .anny-tour-body{color:#cbd5e1;} .anny-tour-step{color:#94a3b8;} .anny-tour-btn{background:#0f172a;color:#e5e7eb;border-color:rgba(255,255,255,0.14);} .anny-tour-btn:hover{background:#111c35;} }';
    document.head.appendChild(style);
  }

  function ensureUI() {
    if (ui.root) return;
    ensureStyles();

    ui.root = document.createElement('div');
    ui.root.id = 'annyTourRoot';
    ui.root.setAttribute('role', 'dialog');
    ui.root.setAttribute('aria-modal', 'true');
    ui.root.setAttribute('aria-hidden', 'true');

    function shade() {
      var d = document.createElement('div');
      d.className = 'anny-tour-shade';
      d.style.left = '0px';
      d.style.top = '0px';
      d.style.width = '0px';
      d.style.height = '0px';
      return d;
    }

    ui.shadeTop = shade();
    ui.shadeLeft = shade();
    ui.shadeRight = shade();
    ui.shadeBottom = shade();

    ui.spotlight = document.createElement('div');
    ui.spotlight.className = 'anny-tour-spotlight';

    ui.tooltip = document.createElement('div');
    ui.tooltip.className = 'anny-tour-tooltip';
    ui.tooltip.setAttribute('role', 'document');

    ui.title = document.createElement('h3');
    ui.title.className = 'anny-tour-title';
    ui.title.id = 'annyTourTitle';

    ui.body = document.createElement('p');
    ui.body.className = 'anny-tour-body';

    var footer = document.createElement('div');
    footer.className = 'anny-tour-footer';

    ui.stepLabel = document.createElement('div');
    ui.stepLabel.className = 'anny-tour-step';

    var actions = document.createElement('div');
    actions.className = 'anny-tour-actions';

    ui.backBtn = document.createElement('button');
    ui.backBtn.className = 'anny-tour-btn';
    ui.backBtn.type = 'button';
    ui.backBtn.textContent = 'Back';

    ui.nextBtn = document.createElement('button');
    ui.nextBtn.className = 'anny-tour-btn anny-tour-btn-primary';
    ui.nextBtn.type = 'button';
    ui.nextBtn.textContent = 'Next';

    ui.skipBtn = document.createElement('button');
    ui.skipBtn.className = 'anny-tour-btn';
    ui.skipBtn.type = 'button';
    ui.skipBtn.textContent = 'Skip';

    actions.appendChild(ui.backBtn);
    actions.appendChild(ui.nextBtn);
    actions.appendChild(ui.skipBtn);

    footer.appendChild(ui.stepLabel);
    footer.appendChild(actions);

    ui.tooltip.appendChild(ui.title);
    ui.tooltip.appendChild(ui.body);
    ui.tooltip.appendChild(footer);

    ui.root.appendChild(ui.shadeTop);
    ui.root.appendChild(ui.shadeLeft);
    ui.root.appendChild(ui.shadeRight);
    ui.root.appendChild(ui.shadeBottom);
    ui.root.appendChild(ui.spotlight);
    ui.root.appendChild(ui.tooltip);

    document.body.appendChild(ui.root);

    ui.backBtn.addEventListener('click', function () {
      goRelative(-1);
    });
    ui.nextBtn.addEventListener('click', function () {
      goRelative(1);
    });
    ui.skipBtn.addEventListener('click', function () {
      stop(true);
    });

    window.addEventListener(
      'resize',
      function () {
        scheduleUpdate();
      },
      { passive: true }
    );
    window.addEventListener(
      'scroll',
      function () {
        scheduleUpdate();
      },
      { passive: true, capture: true }
    );
    document.addEventListener('keydown', function (e) {
      if (!isActive()) return;
      try {
        if (e.key === 'Escape') stop(false);
        if (e.key === 'ArrowRight') goRelative(1);
        if (e.key === 'ArrowLeft') goRelative(-1);
      } catch (_) {}
    });
  }

  function hideUI() {
    if (!ui.root) return;
    try {
      ui.root.style.display = 'none';
      ui.root.setAttribute('aria-hidden', 'true');
    } catch (_) {}
  }

  function showUI() {
    ensureUI();
    try {
      ui.root.style.display = 'block';
      ui.root.setAttribute('aria-hidden', 'false');
      ui.root.setAttribute('aria-labelledby', 'annyTourTitle');
    } catch (_) {}
  }

  function scheduleUpdate() {
    if (state.updateTimer) return;
    state.updateTimer = setTimeout(function () {
      state.updateTimer = null;
      updateLayout();
    }, 50);
  }

  function setShades(rect, viewportW, viewportH) {
    // Top
    ui.shadeTop.style.left = '0px';
    ui.shadeTop.style.top = '0px';
    ui.shadeTop.style.width = viewportW + 'px';
    ui.shadeTop.style.height = rect.top + 'px';
    // Left
    ui.shadeLeft.style.left = '0px';
    ui.shadeLeft.style.top = rect.top + 'px';
    ui.shadeLeft.style.width = rect.left + 'px';
    ui.shadeLeft.style.height = rect.height + 'px';
    // Right
    ui.shadeRight.style.left = rect.left + rect.width + 'px';
    ui.shadeRight.style.top = rect.top + 'px';
    ui.shadeRight.style.width = Math.max(0, viewportW - (rect.left + rect.width)) + 'px';
    ui.shadeRight.style.height = rect.height + 'px';
    // Bottom
    ui.shadeBottom.style.left = '0px';
    ui.shadeBottom.style.top = rect.top + rect.height + 'px';
    ui.shadeBottom.style.width = viewportW + 'px';
    ui.shadeBottom.style.height = Math.max(0, viewportH - (rect.top + rect.height)) + 'px';
  }

  function updateLayout() {
    if (!isActive() || !ui.root || ui.root.style.display === 'none') return;

    var viewportW = Math.max(0, window.innerWidth || 0);
    var viewportH = Math.max(0, window.innerHeight || 0);

    var step = STEPS[state.currentIndex];
    if (!step) return;

    var target = state.target;
    if (target && (!target.getBoundingClientRect || !document.documentElement.contains(target))) {
      target = null;
      state.target = null;
    }

    var pad = 10;
    var rect;

    if (target) {
      var r = target.getBoundingClientRect();
      rect = {
        left: Math.max(8, Math.round(r.left - pad)),
        top: Math.max(8, Math.round(r.top - pad)),
        width: Math.max(20, Math.round(r.width + pad * 2)),
        height: Math.max(20, Math.round(r.height + pad * 2)),
      };
      if (rect.left + rect.width > viewportW - 8) rect.width = Math.max(20, viewportW - 8 - rect.left);
      if (rect.top + rect.height > viewportH - 8) rect.height = Math.max(20, viewportH - 8 - rect.top);

      ui.spotlight.style.display = 'block';
      ui.spotlight.style.left = rect.left + 'px';
      ui.spotlight.style.top = rect.top + 'px';
      ui.spotlight.style.width = rect.width + 'px';
      ui.spotlight.style.height = rect.height + 'px';

      setShades(rect, viewportW, viewportH);
    } else {
      // No target – cover the screen and center tooltip.
      rect = { left: 0, top: 0, width: 0, height: 0 };
      ui.spotlight.style.display = 'none';
      ui.shadeTop.style.left = '0px';
      ui.shadeTop.style.top = '0px';
      ui.shadeTop.style.width = viewportW + 'px';
      ui.shadeTop.style.height = viewportH + 'px';
      ui.shadeLeft.style.width = '0px';
      ui.shadeRight.style.width = '0px';
      ui.shadeBottom.style.height = '0px';
    }

    // Position tooltip
    try {
      ui.tooltip.style.left = '12px';
      ui.tooltip.style.top = '12px';
      ui.tooltip.style.maxWidth = 'min(420px, calc(100vw - 24px))';
      var tr = ui.tooltip.getBoundingClientRect();
      var tw = tr.width;
      var th = tr.height;
      var margin = 12;

      var topPos;
      if (target && rect.top + rect.height + margin + th <= viewportH) topPos = rect.top + rect.height + margin;
      else if (target && rect.top - margin - th >= 0) topPos = rect.top - margin - th;
      else topPos = Math.max(margin, Math.min(viewportH - th - margin, rect.top + rect.height + margin));

      var leftPos;
      if (target) leftPos = Math.max(margin, Math.min(viewportW - tw - margin, rect.left));
      else leftPos = Math.max(margin, Math.min(viewportW - tw - margin, Math.round((viewportW - tw) / 2)));

      ui.tooltip.style.left = leftPos + 'px';
      ui.tooltip.style.top = topPos + 'px';
    } catch (_) {}
  }

  function bindAdvanceOnClick(index, el) {
    if (!el || !el.addEventListener) return;
    if (state.boundAdvance[index]) return;
    state.boundAdvance[index] = true;
    el.addEventListener(
      'click',
      function () {
        try {
          if (!isActive()) return;
          var cur = getStepIndex();
          if (cur !== index) return;
          setStepIndex(index + 1);
        } catch (_) {}
      },
      true
    );
  }

  function setStepUI(index) {
    var step = STEPS[index];
    if (!step) return;
    ui.title.textContent = step.title || 'Tour';
    ui.body.textContent = step.body || '';
    var displayIndex = 0;
    for (var i = 0; i <= index; i++) {
      if (STEPS[i] && !STEPS[i].passive) displayIndex++;
    }
    if (step.passive) ui.stepLabel.textContent = 'Optional';
    else ui.stepLabel.textContent = 'Step ' + String(displayIndex) + ' of ' + String(NON_PASSIVE_TOTAL);

    ui.backBtn.disabled = index <= 0;
    ui.nextBtn.textContent = nextReachableIndex(index, 1) < 0 ? 'Finish' : 'Next';
  }

  function nextReachableIndex(fromIndex, delta) {
    var next = fromIndex + delta;
    var path = currentPath();
    while (next >= 0 && next < STEPS.length) {
      var step = STEPS[next];
      if (step && step.passive && step.page !== path) {
        next += delta;
        continue;
      }
      return next;
    }
    return -1;
  }

  function tryResolveTarget(step, attempt) {
    if (!step || !step.selector) {
      state.target = null;
      scheduleUpdate();
      return;
    }

    var el = null;
    try {
      el = document.querySelector(step.selector);
    } catch (_) {
      el = null;
    }

    if (el) {
      state.target = el;
      try {
        if (el.scrollIntoView) el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
      } catch (_) {
        try {
          el.scrollIntoView(true);
        } catch (_) {}
      }
      scheduleUpdate();
      return;
    }

    if (attempt >= 20) {
      state.target = null;
      scheduleUpdate();
      return;
    }

    if (state.retryTimer) clearTimeout(state.retryTimer);
    state.retryTimer = setTimeout(function () {
      tryResolveTarget(step, attempt + 1);
    }, 150);
  }

  function showStep(index, opts) {
    if (!isActive()) return;
    ensureUI();

    var i = clampIndex(index);
    var step = STEPS[i];
    if (!step) {
      stop(true);
      return;
    }

    setStepIndex(i);
    state.currentIndex = i;

    var path = currentPath();
    if (step.page !== path) {
      if (opts && opts.navigate) {
        try {
          window.location.href = step.page;
          return;
        } catch (_) {}
      }
      // Do not force navigation when resuming.
      hideUI();
      return;
    }

    showUI();
    setStepUI(i);

    try {
      if (typeof step.before === 'function') step.before();
    } catch (_) {}

    state.target = null;
    tryResolveTarget(step, 0);

    if (step.advanceOnClick && step.selector) {
      try {
        var el = document.querySelector(step.selector);
        if (el) bindAdvanceOnClick(i, el);
      } catch (_) {}
    }

    scheduleUpdate();
    try {
      if (ui.nextBtn && ui.nextBtn.focus) ui.nextBtn.focus();
    } catch (_) {}
  }

  function goRelative(delta) {
    if (!isActive()) return;
    var cur = getStepIndex();
    var next = nextReachableIndex(cur, delta);
    if (next < 0) {
      if (delta > 0) {
        stop(true);
        return;
      }
      next = 0;
    }
    var nextStep = STEPS[next];
    showStep(next, { navigate: !(nextStep && nextStep.passive) });
  }

  function start(options) {
    var stepIndex = 0;
    try {
      if (options && options.step !== undefined) stepIndex = clampIndex(options.step);
    } catch (_) {}
    markActive(true);
    setStepIndex(stepIndex);
    showStep(stepIndex, { navigate: false });
  }

  function stop(markDone) {
    hideUI();
    markActive(false);
    if (markDone) setCookie(DONE_COOKIE, '1', MAX_AGE);
  }

  function resume() {
    if (!isActive()) return;
    var cur = getStepIndex();
    var path = currentPath();
    var step = STEPS[cur];
    if (!step || step.page !== path) {
      var best = findBestStepForPath(path, cur);
      if (best >= 0) {
        setStepIndex(best);
        cur = best;
      } else {
        hideUI();
        return;
      }
    }
    showStep(cur, { navigate: false });
  }

  if (!window.annyTour) {
    window.annyTour = {
      start: start,
      stop: stop,
      resume: resume,
      isActive: isActive,
    };
  }

  // Auto-resume when navigating between pages during an active tour
  if (isActive()) {
    try {
      resume();
    } catch (_) {}
  }
})();
