// PDF.js worker config (if available)
try {
  if (window.pdfjsLib) {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://unpkg.com/pdfjs-dist@4.8.69/build/pdf.worker.min.js";
  }
} catch (e) {}

// Temporary: surface JS errors to help diagnose blank UI
(function(){
  try {
    window.addEventListener('error', function(e){ try { alert('JS error: ' + (e?.message||e)); } catch(_){} });
    window.addEventListener('unhandledrejection', function(e){ try { alert('Unhandled: ' + (e?.reason?.message||e?.reason||e)); } catch(_){} });
  } catch(_) {}
})();

// -------- Backend integration helpers --------
async function getPreviewUrl() {
  const tryHttp = async () => {
    try {
      const res = await fetch('/api/preview');
      const data = await res.json();
      if (res.ok && data && data.data_url) return data.data_url;
    } catch (_) {}
    return null;
  };
  const tryHttpPdf = () => {
    // Fallback to a direct PDF endpoint (file response) to avoid data URL issues
    return '/api/preview_pdf?ts=' + Date.now();
  };
  const tryApi = async () => {
    try { if (window.pywebview?.api?.get_preview_url) return await window.pywebview.api.get_preview_url(); } catch {}
    return null;
  };
  let url = await tryHttp();
  if (!url) url = await tryApi();
  if (!url) url = tryHttpPdf();
  if (!url) {
    const start = Date.now();
    while (Date.now() - start < 2500) { await new Promise(r => setTimeout(r, 150)); url = await tryApi(); if (url) break; }
  }
  return url || "https://unec.edu.az/application/uploads/2014/12/pdf-sample.pdf";
}

async function getViewerSettings() {
  const tryApi = async () => {
    try {
      if (window.pywebview?.api?.get_settings) return await window.pywebview.api.get_settings();
    } catch (_) {}
    return null;
  };
  const tryHttp = async () => {
    try {
      const r = await fetch('/api/settings');
      const d = await r.json();
      return (r.ok && d && typeof d === 'object') ? d : null;
    } catch (_) {}
    return null;
  };
  return (await tryApi()) || (await tryHttp());
}

function resolveNoteFontUrl(fontfile) {
  try {
    const f = (fontfile || '').trim();
    if (!f) return null;
    if (/^(https?:|file:|data:)/i.test(f)) return f;

    // Desktop (pywebview) loads preview.html via file://...; resolve relative to repo root.
    if (typeof window !== 'undefined' && window.location?.protocol === 'file:') {
      const cleaned = f.replace(/\\/g, '/');
      const isAbs = /^[a-zA-Z]:\//.test(cleaned) || cleaned.startsWith('/') || cleaned.startsWith('//');
      if (isAbs) {
        // Absolute filesystem path -> file:// URL
        if (/^[a-zA-Z]:\//.test(cleaned)) return 'file:///' + encodeURI(cleaned);
        if (cleaned.startsWith('/')) return 'file://' + encodeURI(cleaned);
        return 'file:' + encodeURI(cleaned);
      }
      const rel = '../../' + cleaned.replace(/^\/+/, '');
      return new URL(rel, window.location.href).toString();
    }

    // Flask mode: serve `fonts/*` via `/fonts/*`.
    if (f.startsWith('fonts/')) return '/fonts/' + f.slice('fonts/'.length);
    if (f.startsWith('/fonts/')) return f;

    // Fallback: let the backend serve whatever font is currently configured.
    return '/api/note_font?ts=' + Date.now();
  } catch (_) {}
  return null;
}

async function ensureNoteFontLoaded(fontName, fontfile) {
  try {
    const name = (fontName || '').trim();
    const url = resolveNoteFontUrl(fontfile);
    if (!name || !url) return;

    const styleId = '__anny_note_font_face';
    let style = document.getElementById(styleId);
    if (!style) {
      style = document.createElement('style');
      style.id = styleId;
      document.head.appendChild(style);
    }
    style.textContent = `@font-face { font-family: \"${name}\"; src: url(\"${url}\"); font-weight: normal; font-style: normal; }`;

    // Best-effort: wait for font to be available before drawing canvas text.
    if (document.fonts?.load) {
      await document.fonts.load(`16px \"${name}\"`);
    }
  } catch (_) {}
}

async function postJson(path, payload) {
  try {
    const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok && (data.ok !== false), data };
  } catch (err) {
    console.error('[preview] postJson failed', path, err);
    return { ok: false, data: null };
  }
}

async function setNoteRect(uid, x0, y0, x1, y1) {
  if (window.pywebview?.api?.set_note_rect) return await window.pywebview.api.set_note_rect(uid, x0, y0, x1, y1);
  const r = await postJson('/api/set_note_rect', { uid, x0, y0, x1, y1 });
  return r.ok;
}
async function setNoteText(uid, text) {
  if (window.pywebview?.api?.set_note_text) return await window.pywebview.api.set_note_text(uid, text);
  const r = await postJson('/api/set_note_text', { uid, text });
  return r.ok;
}
async function setNoteColor(uid, color) {
  if (window.pywebview?.api?.set_note_color) return await window.pywebview.api.set_note_color(uid, color);
  const r = await postJson('/api/set_note_color', { uid, color });
  return r.ok;
}
async function setNoteFontSize(uid, size) {
  if (window.pywebview?.api?.set_note_fontsize) return await window.pywebview.api.set_note_fontsize(uid, size);
  const r = await postJson('/api/set_note_fontsize', { uid, size });
  return r.ok;
}
async function setNoteRotation(uid, angle) {
  if (window.pywebview?.api?.set_note_rotation) return await window.pywebview.api.set_note_rotation(uid, angle);
  const r = await postJson('/api/set_note_rotation', { uid, angle });
  return r.ok;
}

async function browseForPath(current) {
  if (window.pywebview?.api?.browse_export_path) { const p = await window.pywebview.api.browse_export_path(current || ""); return p || current; }
  return current;
}

async function exportEditedPdf(targetPath) {
  if (window.pywebview?.api?.export_pdf) return await window.pywebview.api.export_pdf(targetPath);

  // Web mode (Flask): download a baked PDF only when exporting.
  try {
    const raw = (targetPath || "annotated.pdf").toString();
    const name = (raw.split(/[\\/]/).pop() || "annotated.pdf").trim() || "annotated.pdf";
    const url = `/api/export_pdf?name=${encodeURIComponent(name)}&ts=${Date.now()}`;
    const res = await fetch(url, { method: 'GET' });
    if (!res.ok) {
      let msg = `Export failed (${res.status})`;
      try {
        const data = await res.json();
        if (data?.error) msg = String(data.error);
      } catch (_) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    const objUrl = URL.createObjectURL(blob);
    a.href = objUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      try { URL.revokeObjectURL(objUrl); } catch (_) {}
      try { a.remove(); } catch (_) {}
    }, 0);
    return true;
  } catch (e) {
    alert('Export failed.\n' + (e?.message || e));
    return false;
  }
}

async function notifyFreezeLayout(on) {
  if (window.pywebview?.api?.set_freeze_layout) { try { await window.pywebview.api.set_freeze_layout(!!on); } catch {} }
}

// -------- PDF viewer logic --------
(function(){
  const hasPdfJs = !!window.pdfjsLib;
  let useImages = !hasPdfJs; // fallback mode flag
  let pdfDoc = null;
  let pageNum = 1;
  let isRendering = false;
  let pendingPage = null;
  let zoom = 1.0; // user zoom multiplier (1.0 = fit)
  const ZOOM_MIN = 0.5, ZOOM_MAX = 4.0, ZOOM_STEP = 0.1;
  const NOTE_PADDING_PTS = 4.0;
  const WRAP_TIGHTNESS = 0.96;
  const LINE_HEIGHT_FACTOR = 1.18;

  const canvas = document.getElementById('pdfCanvas');
  const ctx = canvas.getContext('2d', { alpha: false });
  const canvasWrap = document.getElementById('canvasWrap');
  const imgPage = document.getElementById('imgPage');
  const overlay = document.getElementById('overlay');
  let dragState = null;
  let selectedUid = null;
  let viewerSettings = null;

  const $pageNum = document.getElementById('pageNum');
  const $pageCount = document.getElementById('pageCount');
  const $pageInfo = document.getElementById('pageInfo');

  function setPageInfo() {
    if ($pageNum) $pageNum.textContent = String(pageNum);
    if ($pageCount) $pageCount.textContent = pdfDoc ? String(pdfDoc.numPages) : '—';
  }

  async function loadDocument(url) {
    try { console.log('[preview] loadDocument', (url||'').slice(0, 64)); } catch {}
    try {
      if (!useImages && hasPdfJs) {
        canvasWrap.classList.remove('hidden');
        const loadingTask = pdfjsLib.getDocument({ url, verbosity: 0 });
        pdfDoc = await loadingTask.promise;
        pageNum = Math.min(pageNum, pdfDoc.numPages) || 1;
        setPageInfo();
        await renderPage(pageNum);
      } else {
        document.getElementById('prevBtn').disabled = false;
        document.getElementById('nextBtn').disabled = false;
        await renderFallbackPage(pageNum);
      }
    } catch (e) {
      console.error(e);
      try {
        if (window.pywebview?.api?.render_preview_page) {
          useImages = true;
          document.getElementById('prevBtn').disabled = false;
          document.getElementById('nextBtn').disabled = false;
          await renderFallbackPage(pageNum);
          return;
        }
      } catch {}
      try { alert('Failed to load PDF preview.\n' + (e?.message||'')); } catch(_) { alert('Failed to load PDF preview.'); }
    }
  }

  function setZoomLabel() {
    const z = Math.round(zoom * 100);
    const el = document.getElementById('zoomLabel');
    if (el) el.textContent = z + '%';
  }

async function renderFallbackPage(num) {
    const useApi = !!(window.pywebview?.api?.render_preview_page);
    if (useApi) {
      try { if (!window.__pageCount) { const info = await window.pywebview.api.get_preview_page_count(); window.__pageCount = info?.count || 1; } } catch {}
    } else {
      try {
        if (!window.__pageCount) {
          const r = await fetch('/api/preview_page_count');
          const d = await r.json();
          window.__pageCount = d?.count || 1;
        }
      } catch (_) {}
    }
    pageNum = Math.max(1, Math.min(num, window.__pageCount || 1));
    setPageInfo();
    const w = (canvasWrap.clientWidth - 32) * zoom;
    const h = Math.max(300, window.innerHeight * 0.75) * zoom;
    let res = null;
    if (useApi) {
      res = await window.pywebview.api.render_preview_page(pageNum - 1, Math.max(200, Math.round(w)), Math.max(200, Math.round(h)));
    } else {
      const r = await fetch(`/api/render_preview_page?page=${pageNum - 1}&w=${Math.max(200, Math.round(w))}&h=${Math.max(200, Math.round(h))}`);
      res = await r.json();
      if (!r.ok) throw new Error(res?.error || 'Render failed');
    }
    console.log('[preview] renderFallbackPage', { pageNum, res });
    imgPage.src = res.data_url;
    imgPage.style.width = res.width_px + 'px';
    imgPage.style.height = res.height_px + 'px';
    imgPage.classList.remove('hidden');
    overlay.style.zIndex = '30';
    overlay.style.pointerEvents = 'auto';
    overlay.style.width = res.width_px + 'px';
    overlay.style.height = res.height_px + 'px';
    overlay.style.left = '50%';
    overlay.style.top = '50%';
    overlay.style.transform = 'translate(-50%, -50%)';
    drawOverlay(pageNum, res.width_px, res.height_px, { wpt: res.page_width_pts, hpt: res.page_height_pts });
  }

  async function renderPage(num) {
    if (!pdfDoc) return;
    isRendering = true;
    const page = await pdfDoc.getPage(num);
    const container = document.getElementById('canvasWrap');
    const viewport = page.getViewport({ scale: 1 });
    const base = Math.min((container.clientWidth - 32) / viewport.width, (container.clientHeight - 32) / viewport.height) || 1.25;
    const vp = page.getViewport({ scale: base * zoom });
    canvas.width = vp.width | 0;
    canvas.height = vp.height | 0;
    const renderContext = { canvasContext: ctx, viewport: vp };
    await page.render(renderContext).promise;
    if (overlay) {
      overlay.style.width = vp.width + 'px';
      overlay.style.height = vp.height + 'px';
      overlay.style.left = '50%';
      overlay.style.top = '50%';
      overlay.style.transform = 'translate(-50%, -50%)';
      overlay.style.zIndex = '30';
      overlay.style.pointerEvents = 'auto';
    }
    const textLayerDiv = document.getElementById('textLayer');
    if (textLayerDiv) {
      textLayerDiv.innerHTML = '';
      textLayerDiv.style.width = vp.width + 'px';
      textLayerDiv.style.height = vp.height + 'px';
      textLayerDiv.style.left = '50%';
      textLayerDiv.style.top = '50%';
      textLayerDiv.style.transform = 'translate(-50%, -50%)';
      const textContent = await page.getTextContent();
      pdfjsLib.renderTextLayer({ textContentSource: textContent, container: textLayerDiv, viewport: vp });
    }
    isRendering = false;
    if (pendingPage !== null) { const p = pendingPage; pendingPage = null; renderPage(p); }
    setPageInfo();
    try { drawOverlay(num, vp.width, vp.height, null); } catch (e) { console.error(e); }
  }

  function queueRender(num) { if (isRendering) { pendingPage = num; } else { renderPage(num); } }

  // Controls
  document.getElementById('prevBtn')?.addEventListener('click', async () => { if (pageNum <= 1) return; pageNum--; if (!useImages && hasPdfJs) queueRender(pageNum); else await renderFallbackPage(pageNum); });
  document.getElementById('nextBtn')?.addEventListener('click', async () => {
    if (!useImages && hasPdfJs) { if (!pdfDoc || pageNum >= pdfDoc.numPages) return; pageNum++; queueRender(pageNum); }
    else { if (window.__pageCount && pageNum >= window.__pageCount) return; pageNum++; await renderFallbackPage(pageNum); }
  });
  document.getElementById('refreshBtn')?.addEventListener('click', async () => { await refreshPreview(); });

  // -------- AI: annotate current page (web only) --------
  const $aiBtn = document.getElementById('aiAnnotatePageBtn');
  const $aiModal = document.getElementById('aiPageModal');
  const $aiClose = document.getElementById('aiPageCloseBtn');
  const $aiCancel = document.getElementById('aiPageCancelBtn');
  const $aiRun = document.getElementById('aiPageRunBtn');
  const $aiPrompt = document.getElementById('aiPagePrompt');
  const $aiReset = document.getElementById('aiPageUseOriginalBtn');
  const $aiError = document.getElementById('aiPageError');
  const $aiForm = document.getElementById('aiPageForm');
  const $aiWorking = document.getElementById('aiPageWorking');
  let aiBusy = false;

  function _aiShowError(msg) {
    if ($aiError) {
      $aiError.textContent = msg || 'Request failed.';
      $aiError.classList.remove('hidden');
    } else {
      alert(msg || 'Request failed.');
    }
  }
  function _aiClearError() {
    if ($aiError) {
      $aiError.textContent = '';
      $aiError.classList.add('hidden');
    }
  }
  function _aiSetWorking(on) {
    aiBusy = !!on;
    if ($aiForm) $aiForm.classList.toggle('hidden', !!on);
    if ($aiWorking) $aiWorking.classList.toggle('hidden', !on);
    if ($aiRun) $aiRun.disabled = !!on;
    if ($aiCancel) $aiCancel.disabled = !!on;
    if ($aiClose) $aiClose.disabled = !!on;
    if ($aiPrompt) $aiPrompt.disabled = !!on;
    if ($aiReset) $aiReset.disabled = !!on;
  }
  function _aiOpen(originalPrompt) {
    if (!$aiModal) return;
    _aiClearError();
    _aiSetWorking(false);
    try {
      if ($aiPrompt) {
        const existing = ($aiPrompt.value || '').trim();
        if (!existing) $aiPrompt.value = (originalPrompt || '').toString();
      }
    } catch (_) {}
    $aiModal.style.display = 'flex';
    try { $aiPrompt?.focus(); } catch (_) {}
  }
  function _aiCloseModal() {
    if (!$aiModal) return;
    if (aiBusy) return;
    _aiClearError();
    _aiSetWorking(false);
    $aiModal.style.display = 'none';
  }

  async function _pollJob(jobId) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < 10 * 60 * 1000) {
      try {
        const res = await fetch('/api/job/' + encodeURIComponent(jobId) + '?ts=' + Date.now());
        const data = await res.json().catch(() => ({}));
        if (res.ok && data && data.ok) {
          if (data.status === 'done') return { ok: true, data };
          if (data.status === 'error') return { ok: false, error: (data.error || 'Request failed.') };
        }
      } catch (_) {
        // transient error -> keep polling
      }
      await new Promise(r => setTimeout(r, 800));
    }
    return { ok: false, error: 'This is taking longer than expected. Please try again.' };
  }

  async function _aiRunAnnotatePage() {
    _aiClearError();
    _aiSetWorking(true);
    const pageIndex0 = Math.max(0, (pageNum || 1) - 1);
    const promptText = ($aiPrompt?.value || '').toString();

    try {
      // Desktop mode: use pywebview bridge if available.
      if (window.pywebview?.api?.annotate_page) {
        const r = await window.pywebview.api.annotate_page(pageIndex0, promptText);
        if (r && typeof r === 'object' && r.ok === false) {
          throw new Error(r.error || 'AI annotate failed.');
        }
        if (r === false) {
          throw new Error('AI annotate failed.');
        }
        _aiSetWorking(false);
        _aiCloseModal();
        await refreshPreview();
        return;
      }

      const payload = { page_index: pageIndex0, prompt: promptText };
      const res = await fetch('/api/annotate_page?async=1', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data || !data.ok || !data.job) {
        const msg = (data && data.error) ? String(data.error) : ('Failed to start AI annotations (' + res.status + ')');
        _aiSetWorking(false);
        _aiShowError(msg);
        return;
      }

      const result = await _pollJob(String(data.job));
      if (!result.ok) {
        _aiSetWorking(false);
        _aiShowError(result.error || 'Request failed.');
        return;
      }

      _aiSetWorking(false);
      _aiCloseModal();
      await refreshPreview();
    } catch (e) {
      _aiSetWorking(false);
      _aiShowError(e?.message || String(e));
    }
  }

  if ($aiBtn && $aiModal) {
    $aiBtn.addEventListener('click', async () => {
      try {
        if (!overlayMeta) await loadOverlayMeta();
      } catch (_) {}
      const original = (overlayMeta && typeof overlayMeta === 'object' && overlayMeta.ai_prompt) ? String(overlayMeta.ai_prompt) : '';
      _aiOpen(original);
    });
    $aiClose?.addEventListener('click', _aiCloseModal);
    $aiCancel?.addEventListener('click', _aiCloseModal);
    $aiModal.addEventListener('click', (e) => {
      try {
        if (!aiBusy && e.target === $aiModal) _aiCloseModal();
      } catch (_) {}
    });
    window.addEventListener('keydown', (e) => {
      if (!aiBusy && e.key === 'Escape' && $aiModal.style.display === 'flex') _aiCloseModal();
    });
    $aiReset?.addEventListener('click', async () => {
      try {
        if (!overlayMeta) await loadOverlayMeta();
      } catch (_) {}
      const original = (overlayMeta && typeof overlayMeta === 'object' && overlayMeta.ai_prompt) ? String(overlayMeta.ai_prompt) : '';
      if ($aiPrompt) $aiPrompt.value = original;
    });
    $aiRun?.addEventListener('click', _aiRunAnnotatePage);
  }

  document.getElementById('addBoxBtn')?.addEventListener('click', async () => {
    try {
      if (!overlayMeta) {
        await loadOverlayMeta();
      }
      const pageIndex = Math.max(0, (pageNum || 1) - 1);
      let width = parseFloat(overlay?.dataset.pageWidth || '');
      let height = parseFloat(overlay?.dataset.pageHeight || '');
      if (!isFinite(width) || width <= 0 || !isFinite(height) || height <= 0) {
        const pageInfo = overlayMeta?.pages?.find(p => p.index === pageIndex);
        width = pageInfo?.width || 600;
        height = pageInfo?.height || 800;
      }
      const res = await createManualBoxAt(pageIndex, width / 2, height / 2);
      if (!res || !res.uid) {
        alert('Manual note request failed. Ensure manual mode is active.');
      } else {
        try { alert('Manual note created: ' + JSON.stringify(res)); } catch (_) {}
      }
    } catch (err) {
      console.error('[preview] addBoxBtn click failed', err);
      alert('Manual note request failed.');
    }
  });

  function clampZoom(z) { return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)); }
  async function applyZoom(newZoom) { zoom = clampZoom(newZoom); setZoomLabel(); if (!useImages && hasPdfJs) queueRender(pageNum); else await renderFallbackPage(pageNum); }
  document.getElementById('zoomInBtn')?.addEventListener('click', async () => { await applyZoom(zoom + ZOOM_STEP); });
  document.getElementById('zoomOutBtn')?.addEventListener('click', async () => { await applyZoom(zoom - ZOOM_STEP); });
  document.getElementById('zoomFitBtn')?.addEventListener('click', async () => { await applyZoom(1.0); });

  document.getElementById('legacyBtn')?.addEventListener('click', async () => {
    if (window.pywebview?.api?.open_legacy_preview) { try { await window.pywebview.api.open_legacy_preview(); } catch {} }
    else { alert('Legacy preview is only available in desktop app mode.'); }
  });

  document.getElementById('freezeToggle')?.addEventListener('change', (e) => {
    const on = e.target.checked; notifyFreezeLayout(on); document.getElementById('canvasWrap')?.classList.toggle('dragging', on);
  });
  document.getElementById('autoToggle')?.addEventListener('change', (e) => {
    if (window.pywebview?.api?.set_auto_refresh) { try { window.pywebview.api.set_auto_refresh(!!e.target.checked); } catch {} }
  });
  document.getElementById('browseBtn')?.addEventListener('click', async () => {
    const input = document.getElementById('exportPath');
    if (!input) return;
    input.value = await browseForPath(input.value);
  });
  document.getElementById('exportBtn')?.addEventListener('click', async () => {
    const input = document.getElementById('exportPath');
    const suggested = (input && input.value) ? input.value : "annotated.pdf";
    const path = await browseForPath(suggested);
    if (!path) return;
    if (input) input.value = path;
    const ok = await exportEditedPdf(path);
    if (ok && window.pywebview?.api?.export_pdf) { alert("Export complete:\n" + path); }
  });

  // Edit toolbar
  const $mainTb = document.getElementById('mainToolbar');
  const $editTb = document.getElementById('editToolbar');
  const $editBackBtn = document.getElementById('editBackBtn');
  const $saveEditBtn = document.getElementById('saveEditBtn');
  const $cancelEditBtn = document.getElementById('cancelEditBtn');
  const $editTextInput = document.getElementById('editTextInput');
  const $editColorInput = document.getElementById('editColorInput');
  const $editFontSizeInput = document.getElementById('editFontSizeInput');
  const $editNoteId = document.getElementById('editNoteId');
  function enterEditMode(uid) {
    selectedUid = uid;
    try {
      const p = (overlayMeta?.placements || []).find(x => x.uid === uid);
      $editTextInput.value = (p && p.explanation) || '';
      $editColorInput.value = (p && p.color) || '#ff9800';
      const fsz = (p && p.font_size) || viewerSettings?.note_fontsize || 9.0;
      $editFontSizeInput.value = String(fsz || 9.0);
    } catch (_) {
      $editFontSizeInput.value = $editFontSizeInput.value || '9';
    }
    $editNoteId.textContent = uid ? ('#' + uid) : '';
    $mainTb.classList.add('hidden');
    $editTb.classList.remove('hidden');
  }
  function exitEditMode() { $editTb.classList.add('hidden'); $mainTb.classList.remove('hidden'); $editNoteId.textContent=''; }
  $editBackBtn?.addEventListener('click', exitEditMode);
  $cancelEditBtn?.addEventListener('click', exitEditMode);
  $saveEditBtn?.addEventListener('click', async () => {
    if (!selectedUid) { exitEditMode(); return; }
    const uid = selectedUid;
    const text = $editTextInput.value || '';
    const color = $editColorInput.value || '';
    const fsz = parseFloat($editFontSizeInput.value || '0');
    try {
      const okText = await setNoteText(uid, text);
      const okCol = color ? await setNoteColor(uid, color) : false;
      const okFs = (fsz > 0) ? await setNoteFontSize(uid, fsz) : false;

      const pl = (overlayMeta?.placements || []).find(x => x.uid === uid);
      if (pl) {
        if (okText) pl.explanation = text;
        if (okCol) pl.color = color;
        if (okFs) pl.font_size = fsz;
      }

      // Rebuild overlay (client-side only) so text wrapping/font size updates immediately.
      try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
    } catch (e) {
      console.error(e);
    }
    exitEditMode();
  });

  // Debug button
  const debugBtn = document.getElementById('debugBtn');
  if (debugBtn) debugBtn.addEventListener('click', async () => { try { const state = window.pywebview?.api?.debug_dump_state ? await window.pywebview.api.debug_dump_state() : {}; const meta = overlayMeta || {}; const info = { pageNum, hasPdfJs, overlay: { pages: meta.pages?.length || 0, placements: meta.placements?.length || 0 }, backend: state }; alert('Debug info:\n' + JSON.stringify(info, null, 2)); } catch (e) { alert('Debug failed: ' + (e?.message||e)); } });

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft') { document.getElementById('prevBtn')?.click(); }
    if (e.key === 'ArrowRight') { document.getElementById('nextBtn')?.click(); }
    if (e.key.toLowerCase() === 'r' && !selectedUid) { document.getElementById('refreshBtn')?.click(); }
    if (e.key.toLowerCase() === 'e') { document.getElementById('exportBtn')?.click(); }
    const isMod = e.ctrlKey || e.metaKey;
    if (isMod && (e.key === '+' || e.key === '=')) { e.preventDefault(); applyZoom(zoom + ZOOM_STEP); }
    if (isMod && (e.key === '-' || e.key === '_')) { e.preventDefault(); applyZoom(zoom - ZOOM_STEP); }
    if (isMod && (e.key === '0')) { e.preventDefault(); applyZoom(1.0); }
  });

  // Mouse wheel zoom (with Ctrl/Cmd)
  canvasWrap.addEventListener('wheel', async (e) => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); const dir = e.deltaY > 0 ? -1 : 1; await applyZoom(zoom + dir * (ZOOM_STEP * 2)); }, { passive: false });

  // Auto-resize handling
  let resizeTimer = null;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (!useImages && hasPdfJs) { if (!pdfDoc) return; queueRender(pageNum); } else if (window.pywebview?.api?.render_preview_page) { renderFallbackPage(pageNum); } }, 120); });

  async function refreshPreview() {
    try {
      // Fast preview: render the source PDF page and draw annotations as a live overlay.
      // Baking into the PDF happens on export.
      try {
        const s = await getViewerSettings();
        if (s && typeof s === 'object') {
          viewerSettings = s;
          const fontName = (viewerSettings?.note_fontname || 'AnnotateNote').toString().trim() || 'AnnotateNote';
          await ensureNoteFontLoaded(fontName, viewerSettings?.note_fontfile);
        }
      } catch (_) {}

      useImages = true;
      await loadOverlayMeta();
      try { console.log('[preview] overlayMeta', { pages: overlayMeta?.pages?.length || 0, placements: overlayMeta?.placements?.length || 0 }); } catch {}
      await renderFallbackPage(pageNum);
    } catch (e) {
      console.error(e);
      try { alert('Failed to load PDF preview.\n' + (e?.message||'')); } catch(_) { alert('Failed to load PDF preview.'); }
    }
  }

  // Expose refreshPreview for manual refresh and integrations.
  try {
    window.refreshPreview = refreshPreview;
  } catch (_) {}

  // Initial load
  (async function init() {
    try {
      viewerSettings = await getViewerSettings();
      const fontName = (viewerSettings?.note_fontname || 'AnnotateNote').toString().trim() || 'AnnotateNote';
      await ensureNoteFontLoaded(fontName, viewerSettings?.note_fontfile);
    } catch (_) {}
    try { setZoomLabel(); } catch {}
    await refreshPreview();
    try { if (window.pywebview?.api?.get_freeze_layout) { const on = await window.pywebview.api.get_freeze_layout(); const cb = document.getElementById('freezeToggle'); cb.checked = !!on; cb.dispatchEvent(new Event('change')); } } catch {}
    window.addEventListener('error', (e) => console.error('[preview] window error', e?.message, e?.error));
    window.addEventListener('unhandledrejection', (e) => console.error('[preview] unhandled', e?.reason));
    try {
      attachContextListeners();
      attachSecondaryButtonListeners();
    } catch (err) {
      console.error('[preview] failed to attach context listeners', err);
    }
  })();
  document.addEventListener('pywebviewready', () => { try { refreshPreview(); } catch {} });

  // -------- Overlay logic (drag + edit) --------
  let overlayMeta = null;
  async function getPreviewMeta() {
    const tryApi = async () => { try { if (window.pywebview?.api?.get_preview_meta) return await window.pywebview.api.get_preview_meta(); } catch {} return null; };
    const tryHttp = async () => {
      try {
        const r = await fetch('/api/preview_meta');
        const d = await r.json();
        return d?.pages ? d : null;
      } catch (_) { return null; }
    };
    let meta = await tryApi();
    if (!meta) meta = await tryHttp();
    if (!meta) { const start = Date.now(); while (Date.now() - start < 2500) { await new Promise(r => setTimeout(r, 150)); meta = await tryApi(); if (meta) break; } }
    return meta;
  }
  async function loadOverlayMeta() {
    const meta = await getPreviewMeta();
    if (meta && typeof meta === 'object') {
      meta.manual = !!meta.manual;
      overlayMeta = meta;
    } else {
      overlayMeta = { pages: [], placements: [], manual: false };
    }
    dbg('overlayMeta loaded', overlayMeta);
  }
  let lastContextInfo = null;
  function px(n) { return Math.round(n) + 'px'; }
  function isFrozen() { const cb = document.getElementById('freezeToggle'); return !!(cb && cb.checked); }
  function clampNonNeg(n) { return isFinite(n) && n > 0 ? n : 0; }

  function wrapTextLines(text, maxWidthPx, ctx2d, tightness) {
    const t = (text || '').toString();
    const maxW = Math.max(1, maxWidthPx || 1);
    const tight = (typeof tightness === 'number' && isFinite(tightness)) ? tightness : 1.0;

    const measure = (s) => {
      try {
        return ctx2d.measureText(s).width || 0;
      } catch (_) {
        return 0;
      }
    };

    const lines = [];
    const parts = t.split(/\r?\n/);
    if (!parts.length) return [''];
    for (const para of parts) {
      if (!para) { lines.push(''); continue; }
      const words = para.trim().split(/\s+/).filter(Boolean);
      if (!words.length) { lines.push(''); continue; }
      let cur = words[0] || '';
      for (const w of words.slice(1)) {
        const next = cur ? (cur + ' ' + w) : w;
        if (measure(next) * tight <= maxW) {
          cur = next;
        } else {
          lines.push(cur);
          cur = w;
        }
      }
      lines.push(cur);
    }
    return lines.length ? lines : [''];
  }

  function renderNoteTextCanvas(canvasEl, text, innerW, innerH, fontPx, fontFamily, color) {
    const w = clampNonNeg(innerW);
    const h = clampNonNeg(innerH);
    if (!canvasEl || w <= 0 || h <= 0 || !isFinite(fontPx) || fontPx <= 0) return;

    const dpr = (window.devicePixelRatio || 1);
    canvasEl.width = Math.max(1, Math.floor(w * dpr));
    canvasEl.height = Math.max(1, Math.floor(h * dpr));
    canvasEl.style.width = px(w);
    canvasEl.style.height = px(h);

    const c2 = canvasEl.getContext('2d');
    if (!c2) return;
    try {
      c2.setTransform(dpr, 0, 0, dpr, 0, 0);
      c2.clearRect(0, 0, w, h);
      c2.fillStyle = color || '#ff9800';
      c2.textAlign = 'left';
      c2.textBaseline = 'alphabetic';
      c2.font = `${fontPx}px ${fontFamily || 'sans-serif'}`;
      const lines = wrapTextLines(text, w, c2, WRAP_TIGHTNESS);
      const lh = LINE_HEIGHT_FACTOR * fontPx;
      let y = fontPx;
      for (const ln of lines) {
        if (y > h) break;
        try { c2.fillText(ln || '', 0, y); } catch (_) {}
        y += lh;
      }
    } catch (_) {}
  }

  function drawOverlay(num, canvasW, canvasH, pts) {
    if (!overlayMeta) { if (overlay) overlay.innerHTML=''; return; }
    const pageIndex = (num - 1);
    const pageInfo = overlayMeta.pages?.find(p => p.index === pageIndex) || (pts ? { width: pts.wpt, height: pts.hpt } : null);
    if (!overlay) return;
    overlay.innerHTML='';
    const scaleX = canvasW / (pageInfo?.width || canvasW);
    const scaleY = canvasH / (pageInfo?.height || canvasH);
    overlay.dataset.pageIndex = String(pageIndex);
    overlay.dataset.scaleX = String(scaleX || 1);
    overlay.dataset.scaleY = String(scaleY || 1);
    overlay.dataset.pageWidth = String(pageInfo?.width || canvasW);
    overlay.dataset.pageHeight = String(pageInfo?.height || canvasH);
    const placements = (overlayMeta.placements || []).filter(p => p.page_index === pageIndex);

    // Highlight overlay (fast preview): show where the note refers to.
    // Prefer precise hit rectangles (if available), else fall back to the
    // placement's anchor_rect (block around the hit). Match baked PDF highlight
    // opacity (0.25) from `highlights.py`.
    for (const p of placements) {
      try {
        const rects = (Array.isArray(p.hit_rects) && p.hit_rects.length)
          ? p.hit_rects
          : (p.anchor_rect ? [p.anchor_rect] : []);
        for (const ar of rects) {
          if (!ar || !Array.isArray(ar) || ar.length !== 4) continue;
          const ax0 = ar[0] ?? 0, ay0 = ar[1] ?? 0, ax1 = ar[2] ?? 0, ay1 = ar[3] ?? 0;
          const aw = (ax1 - ax0) * scaleX, ah = (ay1 - ay0) * scaleY;
          if (!(aw > 0) || !(ah > 0)) continue;
          const col = p.highlight_color || p.color || '#ff9800';
          const hl = document.createElement('div');
          hl.className = 'absolute';
          hl.style.left = px(ax0 * scaleX);
          hl.style.top = px(ay0 * scaleY);
          hl.style.width = px(aw);
          hl.style.height = px(ah);
          hl.style.backgroundColor = col;
          hl.style.opacity = '0.25';
          hl.style.pointerEvents = 'none';
          overlay.appendChild(hl);
        }
      } catch (_) {}
    }

    for (const p of placements) {
      const x0 = p.note_rect?.[0] ?? 0, y0 = p.note_rect?.[1] ?? 0, x1 = p.note_rect?.[2] ?? 0, y1 = p.note_rect?.[3] ?? 0;
      const w = (x1 - x0) * scaleX, h = (y1 - y0) * scaleY;
      const left = x0 * scaleX, top = y0 * scaleY;
      const col = p.color || '#ff9800';
      const el = document.createElement('div');
      el.className = 'absolute border-2 bg-transparent';
      el.style.left = px(left); el.style.top = px(top); el.style.width = px(w); el.style.height = px(h);
      el.style.borderColor = col;
      try {
        const rot = typeof p.rotation === 'number' ? p.rotation : 0;
        if (isFinite(rot) && Math.abs(rot) > 0.01) {
          el.style.transformOrigin = '50% 50%';
          el.style.transform = `rotate(${rot}deg)`;
        }
      } catch (_) {}
      el.setAttribute('data-uid', p.uid);
      el.setAttribute('data-x0', String(x0)); el.setAttribute('data-y0', String(y0));
      el.setAttribute('data-x1', String(x1)); el.setAttribute('data-y1', String(y1));
      el.setAttribute('data-sx', String(scaleX)); el.setAttribute('data-sy', String(scaleY));

      // Live text overlay (fast preview) — avoids re-baking notes into the PDF on every change.
      try {
        const padX = NOTE_PADDING_PTS * scaleX;
        const padY = NOTE_PADDING_PTS * scaleY;
        const innerW = Math.max(0, w - 2 * padX);
        const innerH = Math.max(0, h - 2 * padY);
        const fontPts = (typeof p.font_size === 'number' && isFinite(p.font_size) && p.font_size > 0)
          ? p.font_size
          : (typeof viewerSettings?.note_fontsize === 'number' ? viewerSettings.note_fontsize : 9.0);
        const fontPx = fontPts * scaleY;
        const fontName = (viewerSettings?.note_fontname || 'AnnotateNote').toString().trim() || 'AnnotateNote';
        const fontFamily = `"${fontName}", Inter, "Noto Sans", system-ui, sans-serif`;
        const tcv = document.createElement('canvas');
        tcv.className = 'absolute';
        tcv.style.left = px(padX);
        tcv.style.top = px(padY);
        tcv.style.pointerEvents = 'none';
        renderNoteTextCanvas(tcv, (p.explanation || '').toString(), innerW, innerH, fontPx, fontFamily, col);
        el.appendChild(tcv);
      } catch (_) {}

      if (!isFrozen()) {
        const handle = document.createElement('div');
        handle.className = 'resize-handle';
        handle.setAttribute('data-role','resize');
        el.appendChild(handle);
      }
      el.addEventListener('dblclick', () => { enterEditMode(p.uid); });
      overlay.appendChild(el);
    }
  }

  async function createManualBoxAt(pageIndex, pageX, pageY) {
    dbg('createManualBoxAt requested', { pageIndex, pageX, pageY, hasApi: !!(window.pywebview?.api?.create_manual_text_box) });
    if (!window.pywebview?.api?.create_manual_text_box) {
      alert('Manual text boxes are only available in the desktop app.');
      return null;
    }
    try {
      const res = await window.pywebview.api.create_manual_text_box(pageIndex, pageX, pageY);
      dbg('create_manual_text_box result', res);
      try { await loadOverlayMeta(); } catch (_) {}
      try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
      if (res && res.uid) {
        setTimeout(() => enterEditMode(res.uid), 40);
      }
      return res;
    } catch (e) {
      console.error('[preview] create_manual_text_box failed', e);
      alert('Failed to create manual text box.');
      return null;
    }
  }

  function openCtxMenu(x, y, opts) {
    dbg('openCtxMenu', { x, y, opts });
    const m = document.getElementById('ctxMenu');
    if (!m) return;
    const uid = opts?.uid || null;
    const manual = opts?.manual !== undefined ? !!opts.manual : !!(overlayMeta?.manual);
    lastContextInfo = {
      uid,
      manual,
      pageIndex: opts?.pageIndex ?? 0,
      pageX: opts?.pageX ?? 0,
      pageY: opts?.pageY ?? 0,
    };
    m.style.display = 'block';
    m.style.left = px(x);
    m.style.top = px(y);
    const close = () => { m.style.display = 'none'; document.removeEventListener('click', close); lastContextInfo = null; };
    document.addEventListener('click', close);
    const editItem = document.getElementById('ctxEditText');
    if (editItem) {
      if (uid) {
        editItem.style.display = 'block';
        editItem.onclick = () => { close(); enterEditMode(uid); };
      } else {
        editItem.style.display = 'none';
        editItem.onclick = null;
      }
    }
    const addItem = document.getElementById('ctxAddText');
    if (addItem) {
      if (manual) {
        addItem.style.display = 'block';
        addItem.onclick = async () => {
          const info = lastContextInfo;
          close();
          if (!info) return;
          await createManualBoxAt(info.pageIndex, info.pageX, info.pageY);
        };
      } else {
        addItem.style.display = 'none';
        addItem.onclick = null;
      }
    }
  }

  function normalizeTarget(t) {
    if (!t) return null;
    if (t.nodeType === 3) return normalizeTarget(t.parentElement);
    return t;
  }

  async function handleContextMenuEvent(e) {
    let target = e.target;
    target = normalizeTarget(target);
    dbg('contextmenu event', { target, manual: overlayMeta?.manual, dataset: overlay ? { pageIndex: overlay.dataset.pageIndex, scaleX: overlay.dataset.scaleX, scaleY: overlay.dataset.scaleY } : null });
    if (!target) return;
    if (!overlayMeta) {
      try { await loadOverlayMeta(); } catch (_) {}
    }
    const manualEnabled = !!(overlayMeta?.manual);
    const noteEl = target.closest ? target.closest('[data-uid]') : null;
    if (!noteEl && !manualEnabled) {
      console.debug('[preview] contextmenu ignored (manual off)', { target, manual: manualEnabled });
      return;
    }
    console.debug('[preview] contextmenu captured', { manual: manualEnabled, tag: target?.tagName, clientX: e.clientX, clientY: e.clientY, dataset: overlay?.dataset });
    if (!overlay) return;
    e.preventDefault();
    if (!overlay.dataset.scaleX) {
      // ensure overlay metadata reflects current viewport
      drawOverlay(pageNum, overlay.clientWidth || 1, overlay.clientHeight || 1, null);
    }
    let scaleX = parseFloat(overlay.dataset.scaleX || '1');
    let scaleY = parseFloat(overlay.dataset.scaleY || '1');
    if (!isFinite(scaleX) || scaleX === 0) scaleX = 1;
    if (!isFinite(scaleY) || scaleY === 0) scaleY = 1;
    let pageIndex = parseInt(overlay.dataset.pageIndex || '', 10);
    if (!isFinite(pageIndex)) {
      pageIndex = Math.max(0, (pageNum || 1) - 1);
    }
    const rect = overlay.getBoundingClientRect();
    const offsetX = Math.max(0, e.clientX - rect.left);
    const offsetY = Math.max(0, e.clientY - rect.top);
    const opts = {
      uid: noteEl ? noteEl.getAttribute('data-uid') : null,
      manual: manualEnabled,
      pageIndex,
      pageX: offsetX / scaleX,
      pageY: offsetY / scaleY,
    };
    openCtxMenu(e.clientX, e.clientY, opts);
  }

  function attachContextListeners() {
    overlay.addEventListener('contextmenu', (e) => {
      const target = e.target;
      const noteEl = target && target.closest ? target.closest('[data-uid]') : null;
      if (!noteEl) {
        return; // allow default browser menu when not on a note
      }
      e.preventDefault();
      handleContextMenuEvent(e);
    }, true);
  }

  function isSecondaryButton(e) {
    if (!e) return false;
    if (typeof e.button === 'number') return e.button === 2;
    if (typeof e.which === 'number') return e.which === 3;
    return false;
  }

  async function handleSecondaryMouse(e) {
    if (!isSecondaryButton(e)) return;
    e.preventDefault();
    await handleContextMenuEvent(e);
  }

  function attachSecondaryButtonListeners() {
    overlay.addEventListener('mouseup', handleSecondaryMouse, true);
  }

  const DRAG_START_PX = 7;
  function beginDragFromTarget(target, clientX, clientY, pointerId, pointerType) {
    if (isFrozen()) return false;
    const t = target && target.closest ? target.closest('[data-uid]') : null;
    if (!t) return false;
    if (dragState) return true;
    const onHandle = !!(target && target.closest ? target.closest('[data-role="resize"]') : null);
    const uid = t.getAttribute('data-uid');
    const sx = parseFloat(t.getAttribute('data-sx') || '1');
    const sy = parseFloat(t.getAttribute('data-sy') || '1');
    const x0 = parseFloat(t.getAttribute('data-x0') || '0');
    const y0 = parseFloat(t.getAttribute('data-y0') || '0');
    const x1 = parseFloat(t.getAttribute('data-x1') || '0');
    const y1 = parseFloat(t.getAttribute('data-y1') || '0');
    dragState = {
      el: t, uid, sx, sy, x0, y0, x1, y1,
      startX: clientX, startY: clientY,
      mode: (onHandle ? 'resize' : 'move'),
      pointerId: (typeof pointerId === 'number' ? pointerId : null),
      pointerType: (pointerType || 'mouse'),
      moved: false,
    };
    return true;
  }

  overlay.addEventListener('mousedown', (e) => {
    // If Pointer Events are supported, prefer those for both mouse and touch.
    if (typeof window !== 'undefined' && 'PointerEvent' in window) return;
    if (beginDragFromTarget(e.target, e.clientX, e.clientY, null, 'mouse')) {
      e.preventDefault();
    }
  });

  overlay.addEventListener('pointerdown', (e) => {
    // Touch/pen drag support (and modern mouse drag via Pointer Events).
    if (!e) return;
    if (beginDragFromTarget(e.target, e.clientX, e.clientY, e.pointerId, e.pointerType || 'touch')) {
      try { dragState?.el?.setPointerCapture?.(e.pointerId); } catch (_) {}
      e.preventDefault();
    }
  }, { passive: false });

  window.addEventListener('mousemove', (e) => {
    if (!dragState) return;
    if (dragState.pointerId !== null) return;
    const dist = Math.hypot((e.clientX - dragState.startX), (e.clientY - dragState.startY));
    if (!dragState.moved && dist < DRAG_START_PX) return;
    dragState.moved = true;
    const { el, sx, sy, startX, startY, x0, y0, x1, y1, mode } = dragState;
    const dx = (e.clientX - startX) / sx;
    const dy = (e.clientY - startY) / sy;
    if (mode === 'resize') {
      const nx1 = Math.max(x0 + 10, x1 + dx);
      const ny1 = Math.max(y0 + 10, y1 + dy);
      el.style.width = px((nx1 - x0) * sx);
      el.style.height = px((ny1 - y0) * sy);
      el.setAttribute('data-x1', String(nx1));
      el.setAttribute('data-y1', String(ny1));
    } else {
      const nx0 = x0 + dx, ny0 = y0 + dy, nx1 = x1 + dx, ny1 = y1 + dy;
      el.style.left = px(nx0 * sx); el.style.top = px(ny0 * sy);
      el.setAttribute('data-x0', String(nx0));
      el.setAttribute('data-y0', String(ny0));
      el.setAttribute('data-x1', String(nx1));
      el.setAttribute('data-y1', String(ny1));
    }
  });

  window.addEventListener('mouseup', async () => {
    if (!dragState) return;
    if (dragState.pointerId !== null) return;
    if (!dragState.moved) { dragState = null; return; }
    const { uid } = dragState;
    const x0 = parseFloat(dragState.el.getAttribute('data-x0') || '0');
    const y0 = parseFloat(dragState.el.getAttribute('data-y0') || '0');
    const x1 = parseFloat(dragState.el.getAttribute('data-x1') || '0');
    const y1 = parseFloat(dragState.el.getAttribute('data-y1') || '0');
    dragState = null;
    try {
      await setNoteRect(uid, x0, y0, x1, y1);
      const pl = (overlayMeta?.placements || []).find(x => x.uid === uid);
      if (pl) pl.note_rect = [x0, y0, x1, y1];
      try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
    } catch {}
  });

  window.addEventListener('pointermove', (e) => {
    if (!dragState) return;
    if (dragState.pointerId === null) return;
    if (e.pointerId !== dragState.pointerId) return;
    const dist = Math.hypot((e.clientX - dragState.startX), (e.clientY - dragState.startY));
    if (!dragState.moved && dist < DRAG_START_PX) return;
    dragState.moved = true;
    const { el, sx, sy, startX, startY, x0, y0, x1, y1, mode } = dragState;
    const dx = (e.clientX - startX) / sx;
    const dy = (e.clientY - startY) / sy;
    if (mode === 'resize') {
      const nx1 = Math.max(x0 + 10, x1 + dx);
      const ny1 = Math.max(y0 + 10, y1 + dy);
      el.style.width = px((nx1 - x0) * sx);
      el.style.height = px((ny1 - y0) * sy);
      el.setAttribute('data-x1', String(nx1));
      el.setAttribute('data-y1', String(ny1));
    } else {
      const nx0 = x0 + dx, ny0 = y0 + dy, nx1 = x1 + dx, ny1 = y1 + dy;
      el.style.left = px(nx0 * sx); el.style.top = px(ny0 * sy);
      el.setAttribute('data-x0', String(nx0));
      el.setAttribute('data-y0', String(ny0));
      el.setAttribute('data-x1', String(nx1));
      el.setAttribute('data-y1', String(ny1));
    }
    try { e.preventDefault(); } catch (_) {}
  }, { passive: false });

  async function endPointerDrag(e) {
    if (!dragState) return;
    if (dragState.pointerId === null) return;
    if (e && e.pointerId !== dragState.pointerId) return;
    // Touch/pen: treat a tap (no drag) as "edit"
    try { dragState?.el?.releasePointerCapture?.(dragState.pointerId); } catch (_) {}
    if (!dragState.moved) {
      const uid = dragState.uid;
      const pt = (dragState.pointerType || 'mouse');
      const mode = dragState.mode;
      dragState = null;
      if (pt !== 'mouse' && mode !== 'resize' && uid) {
        try { enterEditMode(uid); } catch (_) {}
      }
      return;
    }
    const { uid } = dragState;
    const x0 = parseFloat(dragState.el.getAttribute('data-x0') || '0');
    const y0 = parseFloat(dragState.el.getAttribute('data-y0') || '0');
    const x1 = parseFloat(dragState.el.getAttribute('data-x1') || '0');
    const y1 = parseFloat(dragState.el.getAttribute('data-y1') || '0');
    dragState = null;
    try {
      await setNoteRect(uid, x0, y0, x1, y1);
      const pl = (overlayMeta?.placements || []).find(x => x.uid === uid);
      if (pl) pl.note_rect = [x0, y0, x1, y1];
      try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
    } catch {}
  }

  window.addEventListener('pointerup', endPointerDrag, { passive: true });
  window.addEventListener('pointercancel', endPointerDrag, { passive: true });

  // Shortcuts affecting selected element
  window.addEventListener('keydown', async (e) => {
    if (!selectedUid) return;
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    try {
      if (e.key.toLowerCase() === 'f') {
        const v = prompt('Set font size (pt):');
        if (v) {
          const fs = parseFloat(v);
          const ok = await setNoteFontSize(selectedUid, fs);
          const pl = (overlayMeta?.placements || []).find(x => x.uid === selectedUid);
          if (ok && pl && isFinite(fs) && fs > 0) pl.font_size = fs;
          try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
        }
      } else if (e.key.toLowerCase() === 'c') {
        const v = prompt('Set text color (#RRGGBB or named color):');
        if (v) {
          const col = v.trim();
          const ok = await setNoteColor(selectedUid, col);
          const pl = (overlayMeta?.placements || []).find(x => x.uid === selectedUid);
          if (ok && pl && col) pl.color = col;
          try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
        }
      } else if (e.key.toLowerCase() === 'r') {
        const v = prompt('Set rotation (degrees):');
        if (v) {
          const rot = parseFloat(v);
          const ok = await setNoteRotation(selectedUid, rot);
          const pl = (overlayMeta?.placements || []).find(x => x.uid === selectedUid);
          if (ok && pl && isFinite(rot)) pl.rotation = rot;
          try { drawOverlay(pageNum, overlay?.clientWidth || 1, overlay?.clientHeight || 1, null); } catch (_) {}
        }
      }
    } catch {}
  });

  // Settings button -> open settings page via desktop bridge
  (function(){
    var sbtn = document.getElementById('btnSettings');
    function openSettings(e){
      if (e && e.preventDefault) e.preventDefault();
      try {
        var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
        function fallback(){
          try { if (api && api.get_settings_url) { var u = api.get_settings_url(); if (u) { window.location.href = u; return; } } } catch(_){}
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
  })();
})();
  function dbg(...args) {
    try { console.debug('[preview]', ...args); } catch (_) {}
  }
