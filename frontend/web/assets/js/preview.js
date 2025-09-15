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
  const tryApi = async () => {
    try { if (window.pywebview?.api?.get_preview_url) return await window.pywebview.api.get_preview_url(); } catch {}
    return null;
  };
  let url = await tryApi();
  if (!url) {
    const start = Date.now();
    while (Date.now() - start < 2500) { await new Promise(r => setTimeout(r, 150)); url = await tryApi(); if (url) break; }
  }
  return url || "https://unec.edu.az/application/uploads/2014/12/pdf-sample.pdf";
}

async function browseForPath(current) {
  if (window.pywebview?.api?.browse_export_path) { const p = await window.pywebview.api.browse_export_path(current || ""); return p || current; }
  return current;
}

async function exportEditedPdf(targetPath) {
  if (window.pywebview?.api?.export_pdf) return await window.pywebview.api.export_pdf(targetPath);
  alert("Export hook not connected. Implement window.pywebview.api.export_pdf(path).");
  return false;
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

  const canvas = document.getElementById('pdfCanvas');
  const ctx = canvas.getContext('2d', { alpha: false });
  const canvasWrap = document.getElementById('canvasWrap');
  const imgPage = document.getElementById('imgPage');
  const overlay = document.getElementById('overlay');
  let dragState = null;
  let selectedUid = null;

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
    if (!window.pywebview?.api?.render_preview_page) return;
    try { if (!window.__pageCount) { const info = await window.pywebview.api.get_preview_page_count(); window.__pageCount = info?.count || 1; } } catch {}
    pageNum = Math.max(1, Math.min(num, window.__pageCount || 1));
    setPageInfo();
    const w = (canvasWrap.clientWidth - 32) * zoom;
    const h = Math.max(300, window.innerHeight * 0.75) * zoom;
    const res = await window.pywebview.api.render_preview_page(pageNum - 1, Math.max(200, Math.round(w)), Math.max(200, Math.round(h)));
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
  document.getElementById('browseBtn')?.addEventListener('click', async () => { const input = document.getElementById('exportPath'); input.value = await browseForPath(input.value); });
  document.getElementById('exportBtn')?.addEventListener('click', async () => { const path = document.getElementById('exportPath').value || "annotated.pdf"; const ok = await exportEditedPdf(path); if (ok) { alert("Export complete:\n" + path); } });

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
  function enterEditMode(uid) { selectedUid = uid; try { const p = (overlayMeta?.placements || []).find(x => x.uid === uid); $editTextInput.value = (p && p.explanation) || ''; $editColorInput.value = (p && p.color) || '#ff9800'; } catch {} $editFontSizeInput.value = $editFontSizeInput.value || '9'; $editNoteId.textContent = uid ? ('#' + uid) : ''; $mainTb.classList.add('hidden'); $editTb.classList.remove('hidden'); }
  function exitEditMode() { $editTb.classList.add('hidden'); $mainTb.classList.remove('hidden'); $editNoteId.textContent=''; }
  $editBackBtn?.addEventListener('click', exitEditMode);
  $cancelEditBtn?.addEventListener('click', exitEditMode);
  $saveEditBtn?.addEventListener('click', async () => { if (!selectedUid) { exitEditMode(); return; } const uid = selectedUid; const text = $editTextInput.value || ''; const color = $editColorInput.value || ''; const fsz = parseFloat($editFontSizeInput.value || '0'); try { if (window.pywebview?.api?.set_note_text) { await window.pywebview.api.set_note_text(uid, text); } if (window.pywebview?.api?.set_note_color && color) { await window.pywebview.api.set_note_color(uid, color); const el = overlay.querySelector('[data-uid="'+uid+'"]'); if (el) el.style.borderColor = color; } if (window.pywebview?.api?.set_note_fontsize && fsz > 0) { await window.pywebview.api.set_note_fontsize(uid, fsz); } if (document.getElementById('autoToggle')?.checked) { await refreshPreview(); } } catch (e) { console.error(e); } exitEditMode(); });

  // Debug button
  const debugBtn = document.getElementById('debugBtn');
  if (debugBtn) debugBtn.addEventListener('click', async () => { try { const state = window.pywebview?.api?.debug_dump_state ? await window.pywebview.api.debug_dump_state() : {}; const meta = overlayMeta || {}; const info = { pageNum, hasPdfJs, overlay: { pages: meta.pages?.length || 0, placements: meta.placements?.length || 0 }, backend: state }; alert('Debug info:\n' + JSON.stringify(info, null, 2)); } catch (e) { alert('Debug failed: ' + (e?.message||e)); } });

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft') { document.getElementById('prevBtn')?.click(); }
    if (e.key === 'ArrowRight') { document.getElementById('nextBtn')?.click(); }
    if (e.key.toLowerCase() === 'r') { document.getElementById('refreshBtn')?.click(); }
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
      if (window.pywebview?.api) {
        useImages = true;
        await loadOverlayMeta();
        try { console.log('[preview] overlayMeta', { pages: overlayMeta?.pages?.length || 0, placements: overlayMeta?.placements?.length || 0 }); } catch {}
        await renderFallbackPage(pageNum);
        return;
      }
      const url = await getPreviewUrl();
      const finalUrl = url.startsWith('data:') ? url : (url + (url.includes('?') ? '&' : '?') + '_=' + Date.now());
      await loadDocument(finalUrl);
      await loadOverlayMeta();
      try { console.log('[preview] overlayMeta', { pages: overlayMeta?.pages?.length || 0, placements: overlayMeta?.placements?.length || 0 }); } catch {}
      if (!useImages && hasPdfJs && pdfDoc) { queueRender(pageNum); } else { await renderFallbackPage(pageNum); }
    } catch (e) {
      console.error(e);
      try { alert('Failed to load PDF preview.\n' + (e?.message||'')); } catch(_) { alert('Failed to load PDF preview.'); }
    }
  }

  // Initial load
  (async function init() {
    try { setZoomLabel(); } catch {}
    await refreshPreview();
    try { if (window.pywebview?.api?.get_freeze_layout) { const on = await window.pywebview.api.get_freeze_layout(); const cb = document.getElementById('freezeToggle'); cb.checked = !!on; cb.dispatchEvent(new Event('change')); } } catch {}
    window.addEventListener('error', (e) => console.error('[preview] window error', e?.message, e?.error));
    window.addEventListener('unhandledrejection', (e) => console.error('[preview] unhandled', e?.reason));
  })();
  document.addEventListener('pywebviewready', () => { try { refreshPreview(); } catch {} });

  // -------- Overlay logic (drag + edit) --------
  let overlayMeta = null;
  async function getPreviewMeta() {
    const tryApi = async () => { try { if (window.pywebview?.api?.get_preview_meta) return await window.pywebview.api.get_preview_meta(); } catch {} return null; };
    let meta = await tryApi();
    if (!meta) { const start = Date.now(); while (Date.now() - start < 2500) { await new Promise(r => setTimeout(r, 150)); meta = await tryApi(); if (meta) break; } }
    return meta;
  }
  async function loadOverlayMeta() { overlayMeta = await getPreviewMeta(); }
  function px(n) { return Math.round(n) + 'px'; }
  function isFrozen() { const cb = document.getElementById('freezeToggle'); return !!(cb && cb.checked); }

  function drawOverlay(num, canvasW, canvasH, pts) {
    if (!overlayMeta) { if (overlay) overlay.innerHTML=''; return; }
    const pageIndex = (num - 1);
    const pageInfo = overlayMeta.pages?.find(p => p.index === pageIndex) || (pts ? { width: pts.wpt, height: pts.hpt } : null);
    if (!overlay) return;
    overlay.innerHTML='';
    const scaleX = canvasW / (pageInfo?.width || canvasW);
    const scaleY = canvasH / (pageInfo?.height || canvasH);
    const placements = (overlayMeta.placements || []).filter(p => p.page_index === pageIndex);
    for (const p of placements) {
      const x0 = p.note_rect?.[0] ?? 0, y0 = p.note_rect?.[1] ?? 0, x1 = p.note_rect?.[2] ?? 0, y1 = p.note_rect?.[3] ?? 0;
      const w = (x1 - x0) * scaleX, h = (y1 - y0) * scaleY;
      const left = x0 * scaleX, top = y0 * scaleY;
      const col = p.color || '#ff9800';
      const el = document.createElement('div');
      el.className = 'absolute border-2 bg-transparent';
      el.style.left = px(left); el.style.top = px(top); el.style.width = px(w); el.style.height = px(h);
      el.style.borderColor = col;
      el.setAttribute('data-uid', p.uid);
      el.setAttribute('data-x0', String(x0)); el.setAttribute('data-y0', String(y0));
      el.setAttribute('data-x1', String(x1)); el.setAttribute('data-y1', String(y1));
      el.setAttribute('data-sx', String(scaleX)); el.setAttribute('data-sy', String(scaleY));
      if (!isFrozen()) {
        const handle = document.createElement('div');
        handle.className = 'resize-handle';
        handle.setAttribute('data-role','resize');
        el.appendChild(handle);
      }
      el.addEventListener('contextmenu', (e) => { e.preventDefault(); openCtxMenu(e.clientX, e.clientY, p.uid); });
      el.addEventListener('dblclick', () => { enterEditMode(p.uid); });
      overlay.appendChild(el);
    }
  }

  function openCtxMenu(x, y, uid) {
    const m = document.getElementById('ctxMenu');
    if (!m) return;
    m.style.display = 'block';
    m.style.left = px(x);
    m.style.top = px(y);
    const close = () => { m.style.display = 'none'; document.removeEventListener('click', close); };
    document.addEventListener('click', close);
    const editItem = document.getElementById('ctxEditText');
    if (editItem) {
      editItem.onclick = () => { close(); enterEditMode(uid); };
    }
  }

  overlay.addEventListener('mousedown', (e) => {
    if (isFrozen()) return;
    const t = e.target.closest('[data-uid]');
    if (!t) return;
    const onHandle = !!e.target.closest('[data-role="resize"]');
    const uid = t.getAttribute('data-uid');
    const sx = parseFloat(t.getAttribute('data-sx') || '1');
    const sy = parseFloat(t.getAttribute('data-sy') || '1');
    const x0 = parseFloat(t.getAttribute('data-x0') || '0');
    const y0 = parseFloat(t.getAttribute('data-y0') || '0');
    const x1 = parseFloat(t.getAttribute('data-x1') || '0');
    const y1 = parseFloat(t.getAttribute('data-y1') || '0');
    dragState = { el: t, uid, sx, sy, x0, y0, x1, y1, startX: e.clientX, startY: e.clientY, mode: (onHandle ? 'resize' : 'move') };
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!dragState) return;
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
    const { uid } = dragState;
    const x0 = parseFloat(dragState.el.getAttribute('data-x0') || '0');
    const y0 = parseFloat(dragState.el.getAttribute('data-y0') || '0');
    const x1 = parseFloat(dragState.el.getAttribute('data-x1') || '0');
    const y1 = parseFloat(dragState.el.getAttribute('data-y1') || '0');
    dragState = null;
    try {
      if (window.pywebview?.api?.set_note_rect) { await window.pywebview.api.set_note_rect(uid, x0, y0, x1, y1); }
      if (document.getElementById('autoToggle')?.checked) { await refreshPreview(); }
    } catch {}
  });

  // Shortcuts affecting selected element
  window.addEventListener('keydown', async (e) => {
    if (!selectedUid) return;
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    try {
      if (e.key.toLowerCase() === 'f') {
        const v = prompt('Set font size (pt):');
        if (v && window.pywebview?.api?.set_note_fontsize) { await window.pywebview.api.set_note_fontsize(selectedUid, parseFloat(v)); await refreshPreview(); }
      } else if (e.key.toLowerCase() === 'c') {
        const v = prompt('Set text color (#RRGGBB or named color):');
        if (v && window.pywebview?.api?.set_note_color) { await window.pywebview.api.set_note_color(selectedUid, v.trim()); await refreshPreview(); }
      } else if (e.key.toLowerCase() === 'r') {
        const v = prompt('Set rotation (degrees):');
        if (v && window.pywebview?.api?.set_note_rotation) { await window.pywebview.api.set_note_rotation(selectedUid, parseFloat(v)); await refreshPreview(); }
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
