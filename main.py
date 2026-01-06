from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional, Any, Dict
import sys
import subprocess

try:
    import webview  # PyWebView for modern HTML UI bridge
except Exception:  # pragma: no cover - optional dependency
    webview = None  # type: ignore

from UI import WizardApp
from frontend.backend import run_ocr, _remove_background_supported
from frontend.defaults import DEFAULTS
from frontend.settings_store import get_effective_settings, save_user_settings, reset_user_settings
from frontend.colors import build_color_map
from highlights import highlight_and_margin_comment_pdf, _import_fitz

# Debug flag controlled by env var ANNOTATE_DEBUG=1
DEBUG = str(os.environ.get("ANNOTATE_DEBUG", "")).strip().lower() in ("1", "true", "yes")

_TK_DIALOG_ARG = "--tk-dialog"
_TK_DIALOG_PAYLOAD_ENV = "ANNY_TK_DIALOG_PAYLOAD"

def _log(*args: Any) -> None:
    if DEBUG:
        try:
            print("[Annotate]", *args, flush=True)
        except Exception:
            pass


def _run_tk_dialog_child() -> None:
    payload_b64 = os.environ.get(_TK_DIALOG_PAYLOAD_ENV)
    if not payload_b64:
        return
    try:
        payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return

    method = payload.pop("_method", "askopenfilename")
    options = {k: v for k, v in payload.items() if v is not None}
    filetypes = options.get("filetypes")
    if isinstance(filetypes, list):
        options["filetypes"] = [tuple(item) for item in filetypes]

    result: Any = None
    root = None
    try:
        from tkinter import Tk, filedialog  # deferred import keeps main process lean

        root = Tk()
        root.withdraw()
        dialog = getattr(filedialog, method)
        result = dialog(**options)
        if isinstance(result, tuple):
            result = list(result)
    except Exception:
        result = None
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass

    try:
        json.dump(result, sys.stdout)
    except Exception:
        pass


if _TK_DIALOG_ARG in sys.argv[1:]:
    _run_tk_dialog_child()
    sys.exit(0)


def _spawn_tk_dialog(method: str, **options: Any) -> Optional[Any]:
    """Invoke a Tk file dialog in a helper process and return the result."""

    payload = dict(options)
    payload["_method"] = method
    try:
        payload_encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    except Exception:
        return None

    creationflags = 0
    startupinfo = None
    if sys.platform.startswith("win"):
        try:
            creationflags = 0x08000000  # CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= 0x00000001  # STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        except Exception:
            creationflags = 0
            startupinfo = None

    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(str(Path(__file__).resolve()))
    args.append(_TK_DIALOG_ARG)

    env = os.environ.copy()
    env[_TK_DIALOG_PAYLOAD_ENV] = payload_encoded

    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            creationflags=creationflags,
            startupinfo=startupinfo,
            env=env,
        )
    except Exception as exc:  # pragma: no cover - best effort fallback
        _log("tk dialog spawn failed", type(exc).__name__, str(exc))
        return None

    if proc.returncode != 0:
        _log("tk dialog helper exited with", proc.returncode, proc.stderr.decode(errors="ignore").strip())
        return None

    try:
        output = proc.stdout.decode("utf-8").strip()
    except Exception:
        return None
    if not output:
        return None

    try:
        value = json.loads(output)
    except Exception:
        return None

    if value in (None, "", [], {}):
        return None
    return value


def _fallback_open_dialog(title: str, filetypes: list[tuple[str, str]], allow_multiple: bool = False) -> Optional[list[str]]:
    method = "askopenfilenames" if allow_multiple else "askopenfilename"
    result = _spawn_tk_dialog(method, title=title, filetypes=filetypes)
    if allow_multiple:
        if isinstance(result, list) and result:
            return [str(p) for p in result]
        return None
    if isinstance(result, str) and result:
        return [result]
    return None


def _fallback_save_dialog(title: str, filetypes: list[tuple[str, str]], defaultextension: str, initialfile: str | None) -> Optional[str]:
    result = _spawn_tk_dialog(
        "asksaveasfilename",
        title=title,
        filetypes=filetypes,
        defaultextension=defaultextension,
        initialfile=initialfile,
    )
    if isinstance(result, str) and result:
        return result
    return None


def _resolved_settings() -> Dict[str, Any]:
    settings = get_effective_settings()
    try:
        settings["note_fontname"] = DEFAULTS.get("note_fontname", "AnnotateNote")
        fontfile = settings.get("note_fontfile")
        if isinstance(fontfile, str) and fontfile.strip():
            p = Path(fontfile)
            if not p.is_absolute():
                root = _app_root()
                candidate = (root / p).resolve()
                settings["note_fontfile"] = str(candidate)
    except Exception:
        pass
    return settings


def _app_root() -> Path:
    """Return the directory where bundled resources are stored.

    - In normal execution, this is the directory containing this file.
    - Under PyInstaller onefile, files are extracted under ``sys._MEIPASS``.
    - Under PyInstaller onefolder (default in our build), data files live under
      the ``_internal`` folder next to the executable (the default
      --contents-directory).
    """
    try:
        if getattr(sys, "frozen", False):  # running from PyInstaller bundle
            base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
            internal = Path(sys.executable).resolve().parent / "_internal"
            # Prefer the _internal dir if present (onefolder); otherwise MEIPASS
            return internal if internal.exists() else base
    except Exception:
        pass
    return Path(__file__).resolve().parent


# Globals used by exposed API functions
_SELECT_URL: Optional[str] = None
_LOADING_URL: Optional[str] = None
_GET_STARTED_URL: Optional[str] = None
_AI_PROMPT_URL: Optional[str] = None
_AI_WORKING_URL: Optional[str] = None
_PREVIEW_URL: Optional[str] = None
_SETTINGS_URL: Optional[str] = None
_SRC_PDF: Optional[str] = None
_OCR_PDF: Optional[str] = None
_ANN_JSON: Optional[str] = None
_PREVIEW_PDF: Optional[str] = None
_FREEZE_LAYOUT: bool = False
_AUTO_REFRESH: bool = True
_PLACEMENTS = None  # type: ignore
_PAGE_SIZES: dict[int, tuple[int, int]] = {}
_FIXED_OVERRIDES: dict[str, tuple[float, float, float, float]] = {}
# Text content overrides (per note)
_NOTE_TEXT_OVERRIDES: dict[str, str] = {}
# Text color overrides (per note)
_NOTE_COLOR_OVERRIDES: dict[str, str] = {}
_NOTE_FONTSIZE_OVERRIDES: dict[str, float] = {}
_ROTATION_OVERRIDES: dict[str, float] = {}
_MANUAL_MODE: bool = False
_MANUAL_UID_COUNTER: int = 0


def _wnd():
    return webview.windows[0] if webview and webview.windows else None


def _reset_annotation_state(manual: bool | None = None) -> None:
    """Reset placement/override state. If manual is provided, also flip mode."""
    global _PLACEMENTS, _FIXED_OVERRIDES, _NOTE_TEXT_OVERRIDES, _NOTE_COLOR_OVERRIDES
    global _NOTE_FONTSIZE_OVERRIDES, _ROTATION_OVERRIDES, _PAGE_SIZES, _PREVIEW_PDF
    global _MANUAL_MODE, _MANUAL_UID_COUNTER
    if manual is not None:
        _MANUAL_MODE = bool(manual)
    _MANUAL_UID_COUNTER = 0
    _PLACEMENTS = [] if _MANUAL_MODE else None
    try:
        _FIXED_OVERRIDES.clear(); _NOTE_TEXT_OVERRIDES.clear(); _NOTE_COLOR_OVERRIDES.clear()
        _NOTE_FONTSIZE_OVERRIDES.clear(); _ROTATION_OVERRIDES.clear()
    except Exception:
        pass
    try:
        _PAGE_SIZES.clear()
    except Exception:
        pass
    _PREVIEW_PDF = None


def _ensure_page_sizes(pdf_path: str) -> None:
    global _PAGE_SIZES
    if _PAGE_SIZES:
        return
    try:
        fitz = _import_fitz()
        doc = fitz.open(pdf_path)
        sizes = {}
        for i, pg in enumerate(doc):
            sizes[i] = (int(pg.rect.width), int(pg.rect.height))
        doc.close()
        _PAGE_SIZES = sizes
        _log("page_sizes", {"count": len(sizes)})
    except Exception as exc:
        _PAGE_SIZES = {}
        _log("page_sizes_failed", type(exc).__name__, str(exc))


def _manual_queries_payload() -> tuple[list[str], dict[str, str]]:
    placements = globals().get('_PLACEMENTS') or []
    queries: list[str] = []
    comments: dict[str, str] = {}
    seen: set[str] = set()
    for pl in placements:
        try:
            uid = getattr(pl, 'uid', None)
            if uid is None:
                uid = pl.get('uid')  # type: ignore[attr-defined]
            q = getattr(pl, 'query', None)
            if q is None:
                q = pl.get('query')  # type: ignore[attr-defined]
        except Exception:
            uid = None; q = None
        if not q:
            q = f"manual_{uid or len(queries)+1}"
            try:
                if hasattr(pl, 'query'):
                    setattr(pl, 'query', q)
                else:
                    pl['query'] = q  # type: ignore[index]
            except Exception:
                pass
        if q not in seen:
            seen.add(q)
            queries.append(q)
        try:
            exp = getattr(pl, 'explanation', '')
        except Exception:
            exp = pl.get('explanation', '') if isinstance(pl, dict) else ''
        comments[q] = str(exp or '')
    if not queries:
        queries = ['__manual__']
        comments['__manual__'] = ''
    return queries, comments


def _next_manual_uid() -> str:
    global _MANUAL_UID_COUNTER
    _MANUAL_UID_COUNTER += 1
    return f"manual_{_MANUAL_UID_COUNTER:04d}"


def _is_manual_mode() -> bool:
    return bool(_MANUAL_MODE)


def begin_ocr() -> bool:
    """Called from select.html when user clicks Upload.

    Returns False if user cancels file selection, True otherwise.
    """
    global _SRC_PDF, _OCR_PDF
    w = _wnd()
    try:
        paths = w.create_file_dialog(  # type: ignore[union-attr]
            webview.OPEN_DIALOG,  # type: ignore[attr-defined]
            allow_multiple=False,
            file_types=(("PDF files (*.pdf)", "*.pdf"), ("All files (*.*)", "*.*")),
        ) if w else None
    except Exception:
        paths = None

    # Fallback to external Tk helper if pywebview dialog is unavailable
    if not paths:
        paths = _fallback_open_dialog(
            title="Choose input PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            allow_multiple=False,
        )

    if not paths:
        return False

    _SRC_PDF = str(paths[0])

    # Reset any previous annotation/placement state when a new PDF is selected
    global _ANN_JSON
    _ANN_JSON = None
    _reset_annotation_state(manual=False)

    # Swap to loading UI after returning to JS to avoid callback race
    if w and _LOADING_URL:
        def _swap():
            ww = _wnd()
            if ww:
                try:
                    ww.load_url(_LOADING_URL)
                except Exception:
                    pass
        try:
            threading.Timer(0.05, _swap).start()
        except Exception:
            pass

    def worker():
        global _OCR_PDF
        try:
            outp = run_ocr(
                input_pdf=_SRC_PDF or "",
                output_pdf=None,
                languages="eng",
                force=False,
                optimize=0,
                deskew=True,
                # Use no background cleaning to preserve the original look
                clean=False,
                custom_tesseract_path=None,
            )
            _OCR_PDF = outp
            _log("OCR complete", {"out": outp})
            w2 = _wnd()
            try:
                # After OCR, continue to Step 2 (web): get started page
                if w2 and _GET_STARTED_URL:
                    w2.load_url(_GET_STARTED_URL)
            except Exception:
                pass
        except Exception as e:
            _log("OCR failed", type(e).__name__, str(e))
            if w and _SELECT_URL:
                try:
                    w.load_url(_SELECT_URL)
                    msg = f"OCR failed: {type(e).__name__}: {e}"
                    msg = msg.replace("\\", "\\\\").replace("'", "\\'")
                    w.evaluate_js(f"alert('{msg}')")
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True).start()
    return True


def _start_webview_flow() -> tuple[Optional[str], Optional[str]]:
    """Launch the full webview-based flow (Steps 1-3). Returns (src_pdf, ocr_pdf) after the window closes."""
    global _SELECT_URL, _LOADING_URL
    if webview is None:
        return None, None

    root = _app_root()
    # Prefer the new upload landing page; fall back to older names if needed
    select_path = (root / "frontend" / "web" / "upload.html")
    if not select_path.exists():
        select_path = (root / "frontend" / "web" / "select.html")
    if not select_path.exists():
        select_path = (root / "frontend" / "web" / "get_started.html")
    _SELECT_URL = select_path.resolve().as_uri()
    _LOADING_URL = (root / "frontend" / "web" / "loading.html").resolve().as_uri()
    # Step 2 (new)
    global _GET_STARTED_URL, _AI_PROMPT_URL, _AI_WORKING_URL, _PREVIEW_URL, _SETTINGS_URL
    _GET_STARTED_URL = (root / "frontend" / "web" / "get_started.html").resolve().as_uri()
    _AI_PROMPT_URL = (root / "frontend" / "web" / "AI" / "annotate_with_ai.html").resolve().as_uri()
    _AI_WORKING_URL = (root / "frontend" / "web" / "AI" / "ai_working.html").resolve().as_uri()
    _PREVIEW_URL = (root / "frontend" / "web" / "preview.html").resolve().as_uri()
    _SETTINGS_URL = (root / "frontend" / "web" / "settings.html").resolve().as_uri()
    _log("urls", {
        "select": _SELECT_URL,
        "loading": _LOADING_URL,
        "get_started": _GET_STARTED_URL,
        "ai_prompt": _AI_PROMPT_URL,
        "ai_working": _AI_WORKING_URL,
        "preview": _PREVIEW_URL,
        "settings": _SETTINGS_URL,
    })

    class _JSApi:
        # Step 1: OCR
        def begin_ocr(self):  # pragma: no cover
            return begin_ocr()

        # Step 2: Choose path
        def goto_ai_prompt(self):
            w = _wnd()
            if not (w and _AI_PROMPT_URL):
                return False
            # Defer navigation until after returning value to JS callback
            def _go():
                ww = _wnd()
                try:
                    if ww and _AI_PROMPT_URL:
                        ww.load_url(_AI_PROMPT_URL)
                except Exception:
                    pass
            try:
                threading.Timer(0.05, _go).start()
            except Exception:
                pass
            return True

        def choose_annotations_json(self):
            """Open a file dialog to pick annotations JSON, then go to preview."""
            w = _wnd()
            p: Optional[str] = None
            try:
                paths = w.create_file_dialog(  # type: ignore[union-attr]
                    webview.OPEN_DIALOG,  # type: ignore[attr-defined]
                    allow_multiple=False,
                    file_types=(("JSON files (*.json)", "*.json"), ("All files (*.*)", "*.*")),
                ) if w else None
                if paths:
                    p = str(paths[0])
            except Exception:
                pass

            if not p:
                fallback = _fallback_open_dialog(
                    title="Choose annotations JSON",
                    filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                )
                if fallback:
                    p = fallback[0]

            if not p:
                return False

            # Record and move to preview
            global _ANN_JSON
            _ANN_JSON = p
            _reset_annotation_state(manual=False)
            # Important: navigate AFTER returning value to JS to avoid callback teardown
            def _go():
                ww = _wnd()
                try:
                    if ww and _PREVIEW_URL:
                        ww.load_url(_PREVIEW_URL)
                except Exception:
                    pass
            try:
                threading.Timer(0.05, _go).start()
            except Exception:
                pass
            return True

        def start_manual_mode(self):
            """Skip annotations and jump directly to manual placement mode."""
            pdf_path = _OCR_PDF or _SRC_PDF
            if not pdf_path:
                return False
            global _ANN_JSON
            _ANN_JSON = None
            _reset_annotation_state(manual=True)
            try:
                _ensure_page_sizes(pdf_path)
            except Exception:
                pass

            _log("start_manual_mode", {"pdf": pdf_path, "manual": _MANUAL_MODE})
            w = _wnd()
            def _go():
                ww = _wnd()
                try:
                    if ww and _PREVIEW_URL:
                        ww.load_url(_PREVIEW_URL)
                except Exception:
                    pass
            try:
                threading.Timer(0.05, _go).start()
            except Exception:
                pass
            return True

        # Step 2 (AI): Start Gemini generation from prompt
        def start_gemini(self, prompt: str, model: str = "gemini-2.5-flash", max_items: int = 12):
            w = _wnd()
            if not (_SRC_PDF or _OCR_PDF):
                if w:
                    try:
                        w.evaluate_js("alert('No PDF selected. Please go back and choose a PDF first.')")
                    except Exception:
                        pass
                return False

            # Navigate to working page shortly AFTER return to JS to keep callback intact
            def _go_working():
                ww = _wnd()
                try:
                    if ww and _AI_WORKING_URL:
                        ww.load_url(_AI_WORKING_URL)
                except Exception:
                    pass
            try:
                threading.Timer(0.05, _go_working).start()
            except Exception:
                pass

            def _extract_pdf_text_to_temp(pdf_path: str) -> Optional[str]:
                try:
                    fitz = _import_fitz()
                    doc = fitz.open(pdf_path)
                    parts = []
                    for pg in doc:
                        try:
                            parts.append(pg.get_text("text"))
                        except Exception:
                            parts.append(pg.get_text())
                    doc.close()
                    fd, tmp = tempfile.mkstemp(suffix="_gemini_src.txt")
                    os.close(fd)
                    Path(tmp).write_text("\n\n".join(parts), encoding="utf-8")
                    return tmp
                except Exception:
                    return None

            def worker():
                global _ANN_JSON
                pdf_path = _OCR_PDF or _SRC_PDF or ""
                txt_path = _extract_pdf_text_to_temp(pdf_path)
                if not txt_path:
                    try:
                        if w and _AI_PROMPT_URL:
                            w.load_url(_AI_PROMPT_URL)
                            w.evaluate_js("alert('Failed to extract text from PDF for Gemini.')")
                    except Exception:
                        pass
                    return

                # Default outfile next to the PDF
                out_json = str(Path(pdf_path).with_suffix("")) + "__annotations.json"
                try:
                    # Lazy import to avoid hard dependency when user chooses JSON path
                    from models.gemini_annotaton import annotate_txt_file as gemini_annotate
                    gemini_annotate(
                        txt_path=txt_path,
                        objective=(prompt or "").strip(),
                        outfile=out_json,
                        model=(model or "gemini-2.5-flash").strip(),
                        max_items_hint=int(max_items or 12),
                    )
                except Exception as e:
                    # Back to prompt page with error
                    try:
                        if w and _AI_PROMPT_URL:
                            w.load_url(_AI_PROMPT_URL)
                            msg = f"Gemini failed: {type(e).__name__}: {e}"
                            msg = msg.replace("\\", "\\\\").replace("'", "\\'")
                            w.evaluate_js(f"alert('{msg}')")
                    except Exception:
                        pass
                    return

                _ANN_JSON = out_json
                _reset_annotation_state(manual=False)
                # Go to preview page
                try:
                    ww = _wnd()
                    if ww and _PREVIEW_URL:
                        ww.load_url(_PREVIEW_URL)
                except Exception:
                    pass

            try:
                threading.Thread(target=worker, daemon=True).start()
                return True
            except Exception:
                return False

        # -------- Preview bridge (used by preview.html) --------
        def get_preview_url(self) -> str:
            """Build a preview PDF and return a data URL (base64) for the viewer."""
            pdf_path = _OCR_PDF or _SRC_PDF
            ann = _ANN_JSON
            manual = _is_manual_mode()
            if not pdf_path or (not ann and not manual):
                _log("get_preview_url:missing", {"pdf": bool(pdf_path), "ann": bool(ann), "manual": manual})
                raise RuntimeError("Missing PDF or annotations input.")
            _log("get_preview_url", {"pdf": pdf_path, "ann": ann, "manual": manual})

            # Prepare output path in temp dir
            fd, tmp_pdf = tempfile.mkstemp(suffix="_preview.pdf")
            os.close(fd)
            try:
                os.unlink(tmp_pdf)
            except Exception:
                pass

            settings = _resolved_settings()
            # Normalize empty strings to None for colors
            def _none_if_empty(v):
                s = (v or "").strip() if isinstance(v, str) else v
                return None if s == "" else v

            # Ensure placements and page sizes computed once per input
            def _ensure_plan():
                global _PLACEMENTS, _PAGE_SIZES
                if manual:
                    if _PLACEMENTS is None:
                        globals()['_PLACEMENTS'] = []
                    _ensure_page_sizes(pdf_path)
                    return
                if _PLACEMENTS is None:
                    try:
                        _, _hi, _notes, _skipped, placements = highlight_and_margin_comment_pdf(
                            pdf_path=pdf_path,
                            queries=[], comments={}, annotations_json=ann,
                            plan_only=True,
                            note_width=int(settings.get("note_width", 240)),
                            min_note_width=int(settings.get("min_note_width", 48)),
                            note_fontsize=float(settings.get("note_fontsize", 9.0)),
                            note_fill=_none_if_empty(settings.get("note_fill")),
                            note_border=_none_if_empty(settings.get("note_border")),
                            note_border_width=int(settings.get("note_border_width", 0)),
                            note_text=settings.get("note_text", "red"),
                            draw_leader=bool(settings.get("draw_leader", False)),
                            leader_color=_none_if_empty(settings.get("leader_color")),
                            allow_column_footer=bool(settings.get("allow_column_footer", True)),
                            column_footer_max_offset=int(settings.get("column_footer_max_offset", 250)),
                            max_vertical_offset=int(settings.get("max_vertical_offset", 90)),
                            max_scan=int(settings.get("max_scan", 420)),
                            side=settings.get("side", "outer"),
                            allow_center_gutter=bool(settings.get("allow_center_gutter", True)),
                            center_gutter_tolerance=float(settings.get("center_gutter_tolerance", 48.0)),
                            dedupe_scope=str(settings.get("dedupe_scope", "page")),
                            note_fontname=settings.get("note_fontname", DEFAULTS.get("note_fontname", "AnnotateNote")),
                            note_fontfile=settings.get("note_fontfile"),
                        )
                        globals()['_PLACEMENTS'] = placements
                        _log("plan_only computed", {"placements": len(placements)})
                    except Exception as e:
                        raise RuntimeError(f"Failed to compute placements: {type(e).__name__}: {e}")
                if not _PAGE_SIZES:
                    _ensure_page_sizes(pdf_path)

            _ensure_plan()

            try:
                # Build with exact placements and any overrides applied
                fixed = dict(_FIXED_OVERRIDES)

                # Convert stored placements (note_rect tuples) into objects with fitz.Rect
                frz = []
                try:
                    fitz = _import_fitz()
                    pls = globals().get('_PLACEMENTS') or []
                    for pl in pls:
                        try:
                            # Prefer attribute access; only fall back to dict if attrs are missing
                            uid = getattr(pl, 'uid', None)
                            if uid is None:
                                uid = pl.get('uid')  # type: ignore[attr-defined]
                            pg_attr = getattr(pl, 'page_index', None)
                            pg = int(pg_attr if pg_attr is not None else pl.get('page_index'))  # type: ignore[attr-defined]
                            rect_val = getattr(pl, 'note_rect', None)
                            if rect_val is None:
                                rect_val = pl.get('note_rect')  # type: ignore[attr-defined]
                            if isinstance(rect_val, (list, tuple)) and len(rect_val) == 4:
                                rect_obj = fitz.Rect(*rect_val)
                            else:
                                rect_obj = fitz.Rect(float(rect_val.x0), float(rect_val.y0), float(rect_val.x1), float(rect_val.y1))
                            q = getattr(pl, 'query', None)
                            if q is None:
                                q = pl.get('query')  # type: ignore[attr-defined]
                            exp = getattr(pl, 'explanation', None)
                            if exp is None:
                                exp = pl.get('explanation')  # type: ignore[attr-defined]
                            # Apply per-note text override if present
                            try:
                                exp_override = globals().get('_NOTE_TEXT_OVERRIDES', {}).get(str(uid))
                                if exp_override is not None:
                                    exp = exp_override
                            except Exception:
                                pass
                            P = type('P', (), {})
                            p = P()
                            p.uid = uid; p.page_index = pg; p.query = q; p.explanation = exp; p.note_rect = rect_obj
                            frz.append(p)
                        except Exception:
                            continue
                except Exception:
                    frz = []

                queries = []
                comments = {}
                if manual:
                    queries, comments = _manual_queries_payload()

                _log("render_preview", {
                    "fixed": len(_FIXED_OVERRIDES or {}),
                    "text_over": len(_NOTE_TEXT_OVERRIDES or {}),
                    "color_over": len(_NOTE_COLOR_OVERRIDES or {}),
                    "fs_over": len(_NOTE_FONTSIZE_OVERRIDES or {}),
                    "rot_over": len(_ROTATION_OVERRIDES or {}),
                })
                highlight_and_margin_comment_pdf(
                    pdf_path=pdf_path,
                    queries=queries,
                    comments=comments,
                    annotations_json=ann if not manual else None,
                    out_path=tmp_pdf,
                    note_width=int(settings.get("note_width", 240)),
                    min_note_width=int(settings.get("min_note_width", 48)),
                    note_fontsize=float(settings.get("note_fontsize", 9.0)),
                    note_fill=_none_if_empty(settings.get("note_fill")),
                    note_border=_none_if_empty(settings.get("note_border")),
                    note_border_width=int(settings.get("note_border_width", 0)),
                    note_text=settings.get("note_text", "red"),
                    draw_leader=bool(settings.get("draw_leader", False)),
                    leader_color=_none_if_empty(settings.get("leader_color")),
                    allow_column_footer=bool(settings.get("allow_column_footer", True)),
                    column_footer_max_offset=int(settings.get("column_footer_max_offset", 250)),
                    max_vertical_offset=int(settings.get("max_vertical_offset", 90)),
                    max_scan=int(settings.get("max_scan", 420)),
                    side=settings.get("side", "outer"),
                    allow_center_gutter=bool(settings.get("allow_center_gutter", True)),
                    center_gutter_tolerance=float(settings.get("center_gutter_tolerance", 48.0)),
                    dedupe_scope=str(settings.get("dedupe_scope", "page")),
                    note_fontname=settings.get("note_fontname", DEFAULTS.get("note_fontname", "AnnotateNote")),
                    note_fontfile=settings.get("note_fontfile"),
                    # Preview-exact knobs
                    freeze_placements=frz,
                    fixed_note_rects=fixed,
                    # Per-note style overrides
                    note_text_overrides=dict(_NOTE_COLOR_OVERRIDES),
                    note_fontsize_overrides=dict(_NOTE_FONTSIZE_OVERRIDES),
                    note_rotations=dict(_ROTATION_OVERRIDES),
                    rotate_text_with_box=True,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to generate preview: {type(e).__name__}: {e}")

            global _PREVIEW_PDF
            _PREVIEW_PDF = tmp_pdf
            _log("preview_pdf", tmp_pdf)

            # Encode to data URL for safe loading by PDF.js
            import base64
            try:
                data = Path(tmp_pdf).read_bytes()
                b64 = base64.b64encode(data).decode('ascii')
                return f"data:application/pdf;base64,{b64}"
            except Exception as e:
                # Fallback to file:// URI if encoding failed
                return Path(tmp_pdf).resolve().as_uri()

        def get_current_pdf_info(self):
            path = _OCR_PDF or _SRC_PDF
            if not path:
                return {"path": None, "basename": None, "used_ocr": False}
            p = Path(path)
            return {"path": str(p), "basename": p.name, "used_ocr": bool(_OCR_PDF)}

        def get_preview_meta(self):
            pdf_path = _OCR_PDF or _SRC_PDF
            ann = _ANN_JSON
            manual = _is_manual_mode()
            if not pdf_path or (not ann and not manual):
                return {"pages": [], "placements": []}
            settings = _resolved_settings()

            # Ensure plan + sizes exist (without building a baked preview PDF).
            if manual:
                if globals().get("_PLACEMENTS") is None:
                    globals()["_PLACEMENTS"] = []
            else:
                if globals().get("_PLACEMENTS") is None:
                    try:
                        _, _hi, _notes, _skipped, placements = highlight_and_margin_comment_pdf(
                            pdf_path=pdf_path,
                            queries=[],
                            comments={},
                            annotations_json=ann,
                            plan_only=True,
                            note_width=int(settings.get("note_width", 240)),
                            min_note_width=int(settings.get("min_note_width", 48)),
                            note_fontsize=float(settings.get("note_fontsize", 9.0)),
                            note_fill=None if not settings.get("note_fill") else settings.get("note_fill"),
                            note_border=None if not settings.get("note_border") else settings.get("note_border"),
                            note_border_width=int(settings.get("note_border_width", 0)),
                            note_text=settings.get("note_text", "red"),
                            draw_leader=bool(settings.get("draw_leader", False)),
                            leader_color=None if not settings.get("leader_color") else settings.get("leader_color"),
                            allow_column_footer=bool(settings.get("allow_column_footer", True)),
                            column_footer_max_offset=int(settings.get("column_footer_max_offset", 250)),
                            max_vertical_offset=int(settings.get("max_vertical_offset", 90)),
                            max_scan=int(settings.get("max_scan", 420)),
                            side=settings.get("side", "outer"),
                            allow_center_gutter=bool(settings.get("allow_center_gutter", True)),
                            center_gutter_tolerance=float(settings.get("center_gutter_tolerance", 48.0)),
                            dedupe_scope=str(settings.get("dedupe_scope", "page")),
                            note_fontname=settings.get("note_fontname", DEFAULTS.get("note_fontname", "AnnotateNote")),
                            note_fontfile=settings.get("note_fontfile"),
                        )
                        globals()["_PLACEMENTS"] = placements
                        _log("meta: plan_only computed", {"placements": len(placements)})
                    except Exception:
                        globals()["_PLACEMENTS"] = []

            if not (globals().get("_PAGE_SIZES") or {}):
                try:
                    _ensure_page_sizes(pdf_path)
                except Exception:
                    pass
            ann_colors = {}
            if not manual:
                try:
                    # Empty fallback lets us distinguish "no color provided" from "color provided".
                    ann_colors = build_color_map(ann, fallback="")
                except Exception:
                    pass
            # Per-note overrides (color and text)
            color_overrides = globals().get('_NOTE_COLOR_OVERRIDES') or {}
            text_overrides = globals().get('_NOTE_TEXT_OVERRIDES') or {}
            fontsize_overrides = globals().get('_NOTE_FONTSIZE_OVERRIDES') or {}
            rotation_overrides = globals().get('_ROTATION_OVERRIDES') or {}
            default_fontsize = float(settings.get("note_fontsize", 9.0))
            default_note_text = str(settings.get("note_text") or "red").strip() or "red"
            default_highlight = "yellow"

            placements = []
            pls = globals().get('_PLACEMENTS') or []
            fixed = globals().get('_FIXED_OVERRIDES', {})
            def _rect_tuple_any(r):
                try:
                    return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                except Exception:
                    pass
                try:
                    t = tuple(float(x) for x in r)
                    if len(t) == 4:
                        return t
                except Exception:
                    pass
                return None

            def _get(pl, attr: str, key: str):
                try:
                    v = getattr(pl, attr)
                    return v
                except Exception:
                    pass
                try:
                    # support dict-like
                    return pl[key]
                except Exception:
                    return None

            for pl in pls:
                try:
                    uid = _get(pl, 'uid', 'uid')
                    pg = _get(pl, 'page_index', 'page_index')
                    rect = _get(pl, 'note_rect', 'note_rect')
                    anchor = _get(pl, 'anchor_rect', 'anchor_rect')
                    if uid is None or pg is None or rect is None:
                        continue
                    pg = int(pg)
                    if uid in fixed:
                        rect = fixed[uid]
                    rt = _rect_tuple_any(rect)
                    if not rt:
                        continue
                    at = None
                    try:
                        if anchor is not None:
                            at = _rect_tuple_any(anchor)
                    except Exception:
                        at = None
                    q = _get(pl, 'query', 'query')
                    exp = _get(pl, 'explanation', 'explanation')
                    # Apply per-note text override if present (used to prefill editor prompt)
                    try:
                        if uid and uid in text_overrides:
                            exp = text_overrides.get(uid) or exp
                    except Exception:
                        pass
                    # Resolve color: per-note override wins over per-query color map
                    ann_col = ""
                    try:
                        ann_col = (str(ann_colors.get(q) or "") if q else "").strip()
                    except Exception:
                        ann_col = ""
                    highlight_col = ann_col or default_highlight
                    col = None
                    try:
                        if uid and uid in color_overrides and color_overrides.get(uid):
                            col = str(color_overrides.get(uid))
                    except Exception:
                        col = None
                    if not col:
                        col = ann_col or default_note_text
                    fsz = default_fontsize
                    try:
                        ov = fontsize_overrides.get(str(uid))
                        if ov is not None and float(ov) > 0:
                            fsz = float(ov)
                    except Exception:
                        pass
                    rot = 0.0
                    try:
                        rv = rotation_overrides.get(str(uid))
                        if rv is not None:
                            rot = float(rv)
                    except Exception:
                        rot = 0.0
                    placements.append({
                        'uid': uid,
                        'page_index': pg,
                        'note_rect': rt,
                        'anchor_rect': at,
                        'query': q,
                        'explanation': exp,
                        'color': col,
                        'highlight_color': highlight_col,
                        'font_size': fsz,
                        'rotation': rot,
                    })
                except Exception:
                    continue
            pages = [{ 'index': i, 'width': w, 'height': h } for i, (w, h) in (globals().get('_PAGE_SIZES') or {}).items()]
            _log("get_preview_meta", {"pages": len(pages), "placements": len(placements), "manual": manual})
            return { 'pages': pages, 'placements': placements, 'manual': manual }

        def get_preview_page_count(self):
            pdf_path = _OCR_PDF or _SRC_PDF
            if not pdf_path:
                return {'count': 0, 'pages': []}
            try:
                _ensure_page_sizes(pdf_path)
            except Exception:
                pass
            sizes = globals().get('_PAGE_SIZES') or {}
            _log("get_preview_page_count", len(sizes))
            return { 'count': len(sizes), 'pages': [{ 'index': i, 'width': w, 'height': h } for i,(w,h) in sizes.items()] }

        def render_preview_page(self, index: int, max_width: int = 1400, max_height: int = 900):
            path = _OCR_PDF or _SRC_PDF
            if not path:
                raise RuntimeError('No source PDF available')
            try:
                fitz = _import_fitz()
                doc = fitz.open(path)
                if index < 0:
                    index = 0
                if index >= len(doc):
                    index = len(doc) - 1
                pg = doc[index]
                wpt = float(pg.rect.width); hpt = float(pg.rect.height)
                # scale to fit within requested box
                mw = max(200, int(max_width)); mh = max(200, int(max_height))
                sx = mw / wpt; sy = mh / hpt
                scale = max(0.2, min(sx if sx < sy else sy, 3.0))
                mat = fitz.Matrix(scale, scale)
                pix = pg.get_pixmap(matrix=mat, alpha=False)
                data = pix.tobytes('png')
                doc.close()
                _log("render_preview_page", {"index": int(index), "px": (pix.width, pix.height), "pts": (wpt, hpt)})
            except Exception as e:
                raise RuntimeError(f'Failed to rasterize page: {type(e).__name__}: {e}')
            import base64
            b64 = base64.b64encode(data).decode('ascii')
            return {
                'index': int(index),
                'data_url': 'data:image/png;base64,' + b64,
                'width_px': int(pix.width),
                'height_px': int(pix.height),
                'page_width_pts': float(wpt),
                'page_height_pts': float(hpt),
            }

        def set_note_rect(self, uid: str, x0: float, y0: float, x1: float, y1: float):
            try:
                _FIXED_OVERRIDES[str(uid)] = (float(x0), float(y0), float(x1), float(y1))
                _log("set_note_rect", uid, (x0, y0, x1, y1))
                return True
            except Exception:
                return False

        def set_note_text(self, uid: str, text: str):
            try:
                _NOTE_TEXT_OVERRIDES[str(uid)] = str(text)
                _log("set_note_text", uid, (text[:60] + '...') if len(text) > 60 else text)
                return True
            except Exception:
                return False

        def set_note_color(self, uid: str, color: str):
            try:
                _NOTE_COLOR_OVERRIDES[str(uid)] = str(color)
                _log("set_note_color", uid, color)
                return True
            except Exception:
                return False

        def set_note_fontsize(self, uid: str, size: float):
            try:
                fs = float(size)
                if fs <= 0:
                    return False
                _NOTE_FONTSIZE_OVERRIDES[str(uid)] = fs
                _log("set_note_fontsize", uid, fs)
                return True
            except Exception:
                return False

        def set_note_rotation(self, uid: str, angle: float):
            try:
                _ROTATION_OVERRIDES[str(uid)] = float(angle)
                _log("set_note_rotation", uid, float(angle))
                return True
            except Exception:
                return False

        def create_manual_text_box(self, page_index: int, x: Optional[float] = None, y: Optional[float] = None) -> Dict[str, Any]:
            _log("create_manual_text_box:request", {"page_index": page_index, "x": x, "y": y, "manual": _MANUAL_MODE})
            pdf_path = _OCR_PDF or _SRC_PDF
            if pdf_path is None:
                raise RuntimeError("No PDF available for manual annotations.")
            if not _is_manual_mode():
                _log("create_manual_text_box:manual_inactive", {})
                raise RuntimeError("Manual mode is not active.")
            try:
                page_index = int(page_index)
            except Exception as exc:
                raise RuntimeError(f"Invalid page index: {exc}")
            _ensure_page_sizes(pdf_path)
            if page_index < 0:
                page_index = 0
            sizes = globals().get('_PAGE_SIZES') or {}
            if not sizes:
                raise RuntimeError("Page sizes unavailable.")
            if page_index not in sizes:
                # Clamp to last page if out of bounds
                page_index = max(0, max(sizes.keys()))
            page_w, page_h = sizes.get(page_index, next(iter(sizes.values())))
            settings = _resolved_settings()
            note_width = float(settings.get("note_width", DEFAULTS.get("note_width", 240)))
            min_width = float(settings.get("min_note_width", DEFAULTS.get("min_note_width", 48)))
            note_width = max(note_width, min_width)
            base_height = float(settings.get("note_fontsize", DEFAULTS.get("note_fontsize", 9.0))) * 6.0
            note_height = max(72.0, base_height)
            margin = 36.0

            placements = globals().get('_PLACEMENTS')
            if placements is None:
                placements = []
                globals()['_PLACEMENTS'] = placements

            fx = None
            fy = None
            if x is not None and y is not None:
                try:
                    fx = float(x)
                    fy = float(y)
                except Exception:
                    fx = fy = None

            if fx is not None and fy is not None and page_w > 0 and page_h > 0:
                x0 = fx - 0.5 * note_width
                y0 = fy - 0.5 * note_height
                max_x = page_w - margin - note_width
                max_y = page_h - margin - note_height
                x0 = max(margin, min(x0, max_x if max_x >= margin else margin))
                y0 = max(margin, min(y0, max_y if max_y >= margin else margin))
                x1 = x0 + note_width
                y1 = y0 + note_height
            else:
                same_page = []
                for pl in placements:
                    pg_val = None
                    try:
                        pg_val = getattr(pl, 'page_index', None)
                    except Exception:
                        pg_val = None
                    if pg_val is None:
                        try:
                            if isinstance(pl, dict):
                                pg_val = pl.get('page_index')
                        except Exception:
                            pg_val = None
                    try:
                        if pg_val is not None and int(pg_val) == page_index:
                            same_page.append(pl)
                    except Exception:
                        continue
                x0 = max(margin, page_w - note_width - margin)
                y0 = margin + len(same_page) * (note_height + 18.0)
                if y0 + note_height + margin > page_h:
                    y0 = max(margin, page_h - note_height - margin)
                x1 = min(page_w - margin, x0 + note_width)
                y1 = min(page_h - margin, y0 + note_height)
                x0 = x1 - note_width
                y0 = y1 - note_height

            uid = _next_manual_uid()
            placement = {
                'uid': uid,
                'page_index': page_index,
                'query': f'manual_{uid}',
                'explanation': '',
                'anchor_rect': None,
                'note_rect': (x0, y0, x1, y1),
            }
            placements.append(placement)
            _FIXED_OVERRIDES[uid] = (x0, y0, x1, y1)
            _NOTE_TEXT_OVERRIDES.pop(uid, None)
            _NOTE_COLOR_OVERRIDES.pop(uid, None)
            _NOTE_FONTSIZE_OVERRIDES.pop(uid, None)
            _ROTATION_OVERRIDES.pop(uid, None)
            globals()['_PLACEMENTS'] = placements
            globals()['_PREVIEW_PDF'] = None
            _log("create_manual_text_box", {"uid": uid, "page": page_index, "rect": (x0, y0, x1, y1)})
            return {
                'uid': uid,
                'page_index': page_index,
                'note_rect': (x0, y0, x1, y1),
            }

        def debug_add_manual_note(self) -> Dict[str, Any]:
            pdf_path = _OCR_PDF or _SRC_PDF
            if not pdf_path:
                return {'ok': False, 'error': 'no_pdf'}
            if not _is_manual_mode():
                _reset_annotation_state(manual=True)
                _log('debug_add_manual_note', {'action': 'forced_manual_mode'})
            try:
                _ensure_page_sizes(pdf_path)
            except Exception as exc:
                return {'ok': False, 'error': f'page_sizes_failed:{type(exc).__name__}'}
            sizes = globals().get('_PAGE_SIZES') or {}
            if not sizes:
                return {'ok': False, 'error': 'no_pages'}
            first_page_index = sorted(sizes.keys())[0]
            page_w, page_h = sizes[first_page_index]
            try:
                note = self.create_manual_text_box(first_page_index, page_w / 2.0, page_h / 2.0)
                return {'ok': True, 'note': note}
            except Exception as exc:
                return {'ok': False, 'error': f'create_failed:{type(exc).__name__}:{exc}'}

        def browse_font_file(self, current: str | None = None) -> str:
            w = _wnd()
            try:
                paths = w.create_file_dialog(  # type: ignore[union-attr]
                    webview.OPEN_DIALOG,  # type: ignore[attr-defined]
                    allow_multiple=False,
                    file_types=(
                        ("Font files (*.ttf;*.otf;*.ttc;*.woff;*.woff2)", "*.ttf;*.otf;*.ttc;*.woff;*.woff2"),
                        ("All files (*.*)", "*.*"),
                    ),
                ) if w else None
                if paths:
                    return str(paths[0])
            except Exception:
                pass

            fallback = _fallback_open_dialog(
                title="Choose font file",
                filetypes=[
                    ("Font files", "*.ttf *.otf *.ttc *.woff *.woff2"),
                    ("All files", "*.*"),
                ],
                allow_multiple=False,
            )
            if fallback:
                return fallback[0]
            return current or ""

        def browse_export_path(self, current: str | None = None) -> str:
            w = _wnd()
            try:
                path = w.create_file_dialog(  # type: ignore[union-attr]
                    webview.SAVE_DIALOG,  # type: ignore[attr-defined]
                    save_filename=current or "annotated.pdf",
                    file_types=(("PDF files (*.pdf)", "*.pdf"), ("All files (*.*)", "*.*")),
                ) if w else None
                if path:
                    return str(path)
            except Exception:
                pass

            fallback = _fallback_save_dialog(
                title="Save annotated PDF as...",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
                defaultextension=".pdf",
                initialfile=current or "annotated.pdf",
            )
            return fallback or current or ""

        def export_pdf(self, target_path: str) -> bool:
            pdf_path = _OCR_PDF or _SRC_PDF
            ann = _ANN_JSON
            manual = _is_manual_mode()
            if not pdf_path or not target_path or (not ann and not manual):
                return False
            settings = _resolved_settings()
            try:
                # Build freeze_placements just like preview (so text overrides are applied)
                frz = []
                try:
                    fitz = _import_fitz()
                    pls = globals().get('_PLACEMENTS') or []
                    for pl in pls:
                        try:
                            uid = getattr(pl, 'uid', None)
                            if uid is None:
                                uid = pl.get('uid')  # type: ignore[attr-defined]
                            pg_attr = getattr(pl, 'page_index', None)
                            pg = int(pg_attr if pg_attr is not None else pl.get('page_index'))  # type: ignore[attr-defined]
                            rect_val = getattr(pl, 'note_rect', None)
                            if rect_val is None:
                                rect_val = pl.get('note_rect')  # type: ignore[attr-defined]
                            if isinstance(rect_val, (list, tuple)) and len(rect_val) == 4:
                                rect_obj = fitz.Rect(*rect_val)
                            else:
                                rect_obj = fitz.Rect(float(rect_val.x0), float(rect_val.y0), float(rect_val.x1), float(rect_val.y1))
                            anchor_val = getattr(pl, 'anchor_rect', None)
                            if anchor_val is None:
                                anchor_val = pl.get('anchor_rect')  # type: ignore[attr-defined]
                            anchor_rect = None
                            try:
                                if isinstance(anchor_val, (list, tuple)) and len(anchor_val) == 4:
                                    anchor_rect = tuple(float(x) for x in anchor_val)
                                elif anchor_val is not None:
                                    anchor_rect = (float(anchor_val.x0), float(anchor_val.y0), float(anchor_val.x1), float(anchor_val.y1))
                            except Exception:
                                anchor_rect = None
                            q = getattr(pl, 'query', None)
                            if q is None:
                                q = pl.get('query')  # type: ignore[attr-defined]
                            exp = getattr(pl, 'explanation', None)
                            if exp is None:
                                exp = pl.get('explanation')  # type: ignore[attr-defined]
                            try:
                                exp_override = globals().get('_NOTE_TEXT_OVERRIDES', {}).get(str(uid))
                                if exp_override is not None:
                                    exp = exp_override
                            except Exception:
                                pass
                            P = type('P', (), {})
                            p = P()
                            p.uid = uid; p.page_index = pg; p.query = q; p.explanation = exp; p.note_rect = rect_obj; p.anchor_rect = anchor_rect
                            frz.append(p)
                        except Exception:
                            continue
                except Exception:
                    frz = []

                queries = []
                comments = {}
                if manual:
                    queries, comments = _manual_queries_payload()

                highlight_and_margin_comment_pdf(
                    pdf_path=pdf_path,
                    queries=queries,
                    comments=comments,
                    annotations_json=ann if not manual else None,
                    out_path=target_path,
                    note_width=int(settings.get("note_width", 240)),
                    min_note_width=int(settings.get("min_note_width", 48)),
                    note_fontsize=float(settings.get("note_fontsize", 9.0)),
                    note_fill=None if not settings.get("note_fill") else settings.get("note_fill"),
                    note_border=None if not settings.get("note_border") else settings.get("note_border"),
                    note_border_width=int(settings.get("note_border_width", 0)),
                    note_text=settings.get("note_text", "red"),
                    draw_leader=bool(settings.get("draw_leader", False)),
                    leader_color=None if not settings.get("leader_color") else settings.get("leader_color"),
                    allow_column_footer=bool(settings.get("allow_column_footer", True)),
                    column_footer_max_offset=int(settings.get("column_footer_max_offset", 250)),
                    max_vertical_offset=int(settings.get("max_vertical_offset", 90)),
                    max_scan=int(settings.get("max_scan", 420)),
                    side=settings.get("side", "outer"),
                    allow_center_gutter=bool(settings.get("allow_center_gutter", True)),
                    center_gutter_tolerance=float(settings.get("center_gutter_tolerance", 48.0)),
                    dedupe_scope=str(settings.get("dedupe_scope", "page")),
                    note_fontname=settings.get("note_fontname", DEFAULTS.get("note_fontname", "AnnotateNote")),
                    note_fontfile=settings.get("note_fontfile"),
                    # Ensure export respects current overrides and positions
                    freeze_placements=frz,
                    fixed_note_rects=dict(_FIXED_OVERRIDES),
                    note_text_overrides=dict(_NOTE_COLOR_OVERRIDES),
                    note_fontsize_overrides=dict(_NOTE_FONTSIZE_OVERRIDES),
                    note_rotations=dict(_ROTATION_OVERRIDES),
                    rotate_text_with_box=True,
                )
                return True
            except Exception:
                return False

        # Optional UI flags
        def set_freeze_layout(self, on: bool):
            global _FREEZE_LAYOUT
            _FREEZE_LAYOUT = bool(on)
            _log("set_freeze_layout", _FREEZE_LAYOUT)
            return True

        def get_freeze_layout(self) -> bool:
            return _FREEZE_LAYOUT

        def set_auto_refresh(self, on: bool):
            global _AUTO_REFRESH
            _AUTO_REFRESH = bool(on)
            _log("set_auto_refresh", _AUTO_REFRESH)
            return True

        def debug_dump_state(self) -> Dict[str, Any]:
            sizes = dict(globals().get('_PAGE_SIZES') or {})
            placements = globals().get('_PLACEMENTS') or []
            info: Dict[str, Any] = {
                'src_pdf': _SRC_PDF,
                'ocr_pdf': _OCR_PDF,
                'ann_json': _ANN_JSON,
                'preview_pdf': _PREVIEW_PDF,
                'page_sizes_count': len(sizes),
                'placements_count': len(placements),
                'freeze_layout': _FREEZE_LAYOUT,
                'auto_refresh': _AUTO_REFRESH,
                'fixed_overrides_count': len(_FIXED_OVERRIDES or {}),
                'text_overrides_count': len(_NOTE_TEXT_OVERRIDES or {}),
                'color_overrides_count': len(_NOTE_COLOR_OVERRIDES or {}),
                'fontsize_overrides_count': len(_NOTE_FONTSIZE_OVERRIDES or {}),
                'rotation_overrides_count': len(_ROTATION_OVERRIDES or {}),
            }
            try:
                if placements:
                    pl = placements[0]
                    info['sample_placement'] = {
                        'uid': getattr(pl, 'uid', None),
                        'page_index': int(getattr(pl, 'page_index', -1)),
                    }
            except Exception:
                pass
            _log("debug_dump_state", info)
            return info

        # Settings: open page, read, save
        def open_settings(self) -> bool:
            _log("open_settings: called", {"has_wnd": bool(_wnd()), "settings_url": _SETTINGS_URL})
            w = _wnd()
            if not (w and _SETTINGS_URL):
                _log("open_settings: missing window or url", {"wnd": bool(w), "url": bool(_SETTINGS_URL)})
                return False
            # Defer navigation slightly to avoid callback teardown race
            def _go():
                ww = _wnd()
                try:
                    if ww and _SETTINGS_URL:
                        _log("open_settings: navigating", _SETTINGS_URL)
                        ww.load_url(_SETTINGS_URL)
                except Exception:
                    pass
            try:
                threading.Timer(0.05, _go).start()
            except Exception:
                return False
            return True

        def get_settings(self) -> Dict[str, Any]:
            try:
                s = get_effective_settings()
                _log("get_settings", s)
                return s
            except Exception:
                return dict(DEFAULTS)

        def save_settings(self, patch: Dict[str, Any]) -> bool:
            try:
                _log("save_settings: incoming", patch)
                ok = bool(save_user_settings(dict(patch or {})))
                _log("save_settings: result", ok)
                return ok
            except Exception:
                return False

        def reset_settings(self) -> bool:
            try:
                ok = reset_user_settings()
                _log("reset_settings", ok)
                return ok
            except Exception:
                return False

        def get_settings_url(self) -> str:
            """Return the settings page URL for JS fallback navigation/debug."""
            u = _SETTINGS_URL or ""
            _log("get_settings_url", u)
            return u

        # Optional: open legacy Tk preview using previous UI behavior
        def open_legacy_preview(self) -> bool:
            pdf_path = _OCR_PDF or _SRC_PDF
            ann = _ANN_JSON
            if not pdf_path or not ann:
                return False
            try:
                root = _app_root()
                runner = (root / 'legacy_preview_runner.py').resolve()
                if not runner.exists():
                    return False
                # Launch detached so it doesn't block the webview
                creationflags = 0
                try:
                    # Windows specific flag to hide console of child process
                    creationflags = 0x08000000  # CREATE_NO_WINDOW
                except Exception:
                    creationflags = 0
                subprocess.Popen([sys.executable, str(runner), str(pdf_path), str(ann)],
                                  cwd=str(root),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=creationflags)
                return True
            except Exception:
                return False

    webview.create_window(
        title="Annotate",
        url=_SELECT_URL,
        width=900,
        height=700,
        resizable=True,
        js_api=_JSApi(),
    )
    try:
        webview.start(debug=DEBUG)
    except TypeError:
        webview.start()
    return _SRC_PDF, _OCR_PDF


def main():
    # Prefer the modern web UI when pywebview is available.
    # Set ANNOTATE_USE_MODERN=0 to force legacy Tk.
    env_modern = os.environ.get("ANNOTATE_USE_MODERN", "").strip().lower()
    use_modern = (env_modern in ("", "1", "true", "yes"))
    if use_modern and webview is not None:
        _start_webview_flow()
        return
    app = WizardApp()
    app.mainloop()


if __name__ == "__main__":
    main()
