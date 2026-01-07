from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, after_this_request, jsonify, redirect, request, send_from_directory, send_file
from werkzeug.utils import secure_filename
import requests

import local_app as state
from frontend.backend import run_ocr
from frontend.defaults import DEFAULTS
from frontend.colors import build_color_map
from frontend.settings_store import get_effective_settings, save_user_settings
from highlights import highlight_and_margin_comment_pdf, _import_fitz
from models.gemini_annotaton import annotate_txt_file

WEB_ROOT = Path(__file__).resolve().parent / "frontend" / "web"
CUSTOM_FONT_ROOT = Path(__file__).resolve().parent / "custom_font_generator"
FONTS_ROOT = Path(__file__).resolve().parent / "fonts"
FONT_MAKER_CACHE_DIR = Path(tempfile.gettempdir()) / "anny_font_maker"
FONT_MAKER_CACHE_MAX_AGE_SECONDS = 60 * 60  # 1 hour

app = Flask(__name__, static_folder=str(WEB_ROOT), static_url_path="")

_FONT_MAKER_INDEX: dict[str, dict[str, object]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, object]] = {}
_JOB_MAX_AGE_SECONDS = 60 * 60  # 1 hour

# Official template from the Handwrite repo (fallback if template PDF isn't shipped).
_HANDWRITE_TEMPLATE_URL = (
    "https://raw.githubusercontent.com/"
    "yashlamba/handwrite/dev/handwrite_sample.pdf"
)


def _none_if_empty(val):
    s = (val or "").strip() if isinstance(val, str) else val
    return None if s == "" else val


def _save_upload(file_obj, fallback_name: str) -> Path:
    name = secure_filename(file_obj.filename or fallback_name) or fallback_name
    tmp_dir = Path(tempfile.mkdtemp(prefix="anny_upload_"))
    dest = tmp_dir / name
    file_obj.save(dest)
    return dest


def _missing_ocr_deps() -> list[str]:
    missing: list[str] = []
    if shutil.which("tesseract") is None:
        missing.append("tesseract")
    if shutil.which("gs") is None:
        missing.append("ghostscript (gs)")
    return missing


def _purge_jobs() -> None:
    now = time.time()
    with _JOBS_LOCK:
        old = [jid for jid, j in _JOBS.items() if (now - float(j.get("created") or now)) > _JOB_MAX_AGE_SECONDS]
        for jid in old:
            _JOBS.pop(jid, None)


def _job_create(kind: str) -> str:
    _purge_jobs()
    jid = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[jid] = {
            "id": jid,
            "kind": kind,
            "status": "queued",
            "created": time.time(),
            "updated": time.time(),
            "next": "",
            "error": "",
        }
    return jid


def _job_update(job_id: str, **fields: object) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated"] = time.time()


def _job_get(job_id: str) -> dict[str, object] | None:
    _purge_jobs()
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


@app.get("/api/job/<job_id>")
def api_job_status(job_id: str):
    job = _job_get(str(job_id))
    if not job:
        return jsonify({"ok": False, "error": "Not Found"}), 404
    return jsonify({"ok": True, **job})


def _build_preview_data_url() -> str:
    pdf_path = state._OCR_PDF or state._SRC_PDF
    ann = state._ANN_JSON
    manual = state._is_manual_mode()
    if not pdf_path or (not ann and not manual):
        state._log("preview:missing", {"pdf": bool(pdf_path), "ann": bool(ann), "manual": manual})
        raise RuntimeError("Missing PDF or annotations input.")
    state._log("preview:start", {"pdf": pdf_path, "ann": ann, "manual": manual})

    fd, tmp_pdf = tempfile.mkstemp(suffix="_preview.pdf")
    os.close(fd)
    try:
        os.unlink(tmp_pdf)
    except Exception:
        pass

    settings = state._resolved_settings()

    def _ensure_plan():
        if manual:
            if state._PLACEMENTS is None:
                state._PLACEMENTS = []
            state._ensure_page_sizes(pdf_path)
            return
        if state._PLACEMENTS is None:
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
                state._PLACEMENTS = placements
                state._log("preview:plan_only", {"placements": len(placements)})
            except Exception as exc:
                raise RuntimeError(f"Failed to compute placements: {type(exc).__name__}: {exc}")
        if not state._PAGE_SIZES:
            state._ensure_page_sizes(pdf_path)

    _ensure_plan()

    try:
        fixed = dict(state._FIXED_OVERRIDES)

        frz = []
        try:
            fitz = _import_fitz()
            pls = state._PLACEMENTS or []
            for pl in pls:
                try:
                    uid = getattr(pl, "uid", None)
                    if uid is None:
                        uid = pl.get("uid")  # type: ignore[attr-defined]
                    pg_attr = getattr(pl, "page_index", None)
                    pg = int(pg_attr if pg_attr is not None else pl.get("page_index"))  # type: ignore[attr-defined]
                    rect_val = getattr(pl, "note_rect", None)
                    if rect_val is None:
                        rect_val = pl.get("note_rect")  # type: ignore[attr-defined]
                    if isinstance(rect_val, (list, tuple)) and len(rect_val) == 4:
                        rect_obj = fitz.Rect(*rect_val)
                    else:
                        rect_obj = fitz.Rect(float(rect_val.x0), float(rect_val.y0), float(rect_val.x1), float(rect_val.y1))
                    q = getattr(pl, "query", None)
                    if q is None:
                        q = pl.get("query")  # type: ignore[attr-defined]
                    exp = getattr(pl, "explanation", None)
                    if exp is None:
                        exp = pl.get("explanation")  # type: ignore[attr-defined]
                    try:
                        exp_override = state._NOTE_TEXT_OVERRIDES.get(str(uid))
                        if exp_override is not None:
                            exp = exp_override
                    except Exception:
                        pass
                    P = type("P", (), {})
                    p = P()
                    p.uid = uid
                    p.page_index = pg
                    p.query = q
                    p.explanation = exp
                    p.note_rect = rect_obj
                    frz.append(p)
                except Exception:
                    continue
        except Exception:
            frz = []

        queries = []
        comments = {}
        if manual:
            queries, comments = state._manual_queries_payload()

        state._log(
            "preview:render",
            {
                "fixed": len(state._FIXED_OVERRIDES or {}),
                "text_over": len(state._NOTE_TEXT_OVERRIDES or {}),
                "color_over": len(state._NOTE_COLOR_OVERRIDES or {}),
                "fs_over": len(state._NOTE_FONTSIZE_OVERRIDES or {}),
                "rot_over": len(state._ROTATION_OVERRIDES or {}),
            },
        )
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
            freeze_placements=frz,
            fixed_note_rects=fixed,
            note_text_overrides=dict(state._NOTE_COLOR_OVERRIDES),
            note_fontsize_overrides=dict(state._NOTE_FONTSIZE_OVERRIDES),
            note_rotations=dict(state._ROTATION_OVERRIDES),
            rotate_text_with_box=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to generate preview: {type(exc).__name__}: {exc}")

    state._PREVIEW_PDF = tmp_pdf
    state._log("preview:ready", tmp_pdf)

    try:
        data = Path(tmp_pdf).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:application/pdf;base64,{b64}"
    except Exception:
        return Path(tmp_pdf).resolve().as_uri()


@app.get("/")
def index():
    return send_from_directory(WEB_ROOT, "upload.html")


@app.post("/api/upload_pdf")
def api_upload_pdf():
    file_obj = request.files.get("file") or request.files.get("pdf")
    if file_obj is None:
        return jsonify({"ok": False, "error": "Missing PDF file"}), 400
    pdf_path = _save_upload(file_obj, "input.pdf")
    state._SRC_PDF = str(pdf_path)
    state._ANN_JSON = None
    state._reset_annotation_state(manual=False)

    async_mode = str(request.args.get("async", "")).strip().lower() in ("1", "true", "yes")

    try:
        missing = _missing_ocr_deps()
        if missing:
            msg = (
                "OCR dependencies are missing on the server: "
                + ", ".join(missing)
                + ".\n\n"
                + "If deploying to Railway, install system packages (e.g. via nixpacks) and redeploy."
            )
            state._log("api:ocr_missing_deps", missing)
            return jsonify({"ok": False, "error": msg}), 500

        if async_mode:
            job_id = _job_create("ocr")
            _job_update(job_id, status="running")

            def _run():
                try:
                    outp = run_ocr(
                        input_pdf=str(pdf_path),
                        output_pdf=None,
                        languages="eng",
                        force=False,
                        optimize=0,
                        deskew=True,
                        clean=False,
                        custom_tesseract_path=None,
                    )
                    state._OCR_PDF = outp
                    state._log("api:ocr_complete", outp)
                    _job_update(job_id, status="done", next="/get_started.html")
                except Exception as exc:
                    try:
                        app.logger.exception("OCR failed")
                    except Exception:
                        pass
                    state._log("api:ocr_failed", type(exc).__name__, str(exc))
                    _job_update(job_id, status="error", error=f"OCR failed: {type(exc).__name__}: {exc}")

            threading.Thread(target=_run, daemon=True).start()
            return jsonify({"ok": True, "job": job_id, "next": f"/loading_ocr.html?job={job_id}"})

        outp = run_ocr(
            input_pdf=str(pdf_path),
            output_pdf=None,
            languages="eng",
            force=False,
            optimize=0,
            deskew=True,
            clean=False,
            custom_tesseract_path=None,
        )
        state._OCR_PDF = outp
        state._log("api:ocr_complete", outp)
    except Exception as exc:
        try:
            app.logger.exception("OCR failed")
        except Exception:
            pass
        state._log("api:ocr_failed", type(exc).__name__, str(exc))
        return jsonify({"ok": False, "error": f"OCR failed: {type(exc).__name__}: {exc}"}), 500

    return jsonify({"ok": True, "next": "/get_started.html", "src_pdf": state._SRC_PDF, "ocr_pdf": state._OCR_PDF})


@app.post("/api/upload_annotations")
def api_upload_annotations():
    file_obj = request.files.get("file") or request.files.get("json")
    if file_obj is None:
        return jsonify({"ok": False, "error": "Missing annotations JSON file"}), 400
    ann_path = _save_upload(file_obj, "annotations.json")
    state._ANN_JSON = str(ann_path)
    state._reset_annotation_state(manual=False)
    return jsonify({"ok": True, "next": "/preview.html", "ann": state._ANN_JSON})


@app.post("/api/start_manual")
def api_start_manual():
    pdf_path = state._OCR_PDF or state._SRC_PDF
    if not pdf_path:
        return jsonify({"ok": False, "error": "Upload a PDF first."}), 400
    state._ANN_JSON = None
    state._reset_annotation_state(manual=True)
    try:
        state._ensure_page_sizes(pdf_path)
    except Exception:
        pass
    return jsonify({"ok": True, "next": "/preview.html"})


@app.get("/api/preview")
def api_preview():
    try:
        url = _build_preview_data_url()
        return jsonify({"ok": True, "data_url": url})
    except Exception as exc:
        state._log("api:preview_failed", type(exc).__name__, str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/preview_pdf")
def api_preview_pdf():
    try:
        _ = _build_preview_data_url()
        if state._PREVIEW_PDF and Path(state._PREVIEW_PDF).exists():
            return send_file(state._PREVIEW_PDF, mimetype="application/pdf")
        return ("Preview not ready", 404)
    except Exception as exc:
        state._log("api:preview_pdf_failed", type(exc).__name__, str(exc))
        return ("Failed to build preview", 400)


@app.get("/api/export_pdf")
def api_export_pdf():
    pdf_path = state._OCR_PDF or state._SRC_PDF
    ann = state._ANN_JSON
    manual = state._is_manual_mode()
    if not pdf_path or (not ann and not manual):
        return jsonify({"ok": False, "error": "Upload a PDF and annotations first."}), 400

    # Ensure placements and page sizes are computed (no baking).
    try:
        _ = _preview_meta()
    except Exception:
        pass

    settings = state._resolved_settings()

    fd, tmp_pdf = tempfile.mkstemp(suffix="_export.pdf")
    os.close(fd)
    try:
        os.unlink(tmp_pdf)
    except Exception:
        pass

    try:
        fixed = dict(state._FIXED_OVERRIDES)

        # Convert stored placements into objects with fitz.Rect (freeze_placements format).
        frz = []
        try:
            fitz = _import_fitz()
            pls = state._PLACEMENTS or []
            for pl in pls:
                try:
                    uid = getattr(pl, "uid", None)
                    if uid is None:
                        uid = pl.get("uid")  # type: ignore[attr-defined]
                    pg_attr = getattr(pl, "page_index", None)
                    pg = int(pg_attr if pg_attr is not None else pl.get("page_index"))  # type: ignore[attr-defined]
                    rect_val = getattr(pl, "note_rect", None)
                    if rect_val is None:
                        rect_val = pl.get("note_rect")  # type: ignore[attr-defined]
                    if isinstance(rect_val, (list, tuple)) and len(rect_val) == 4:
                        rect_obj = fitz.Rect(*rect_val)
                    else:
                        rect_obj = fitz.Rect(float(rect_val.x0), float(rect_val.y0), float(rect_val.x1), float(rect_val.y1))
                    anchor_val = getattr(pl, "anchor_rect", None)
                    if anchor_val is None:
                        anchor_val = pl.get("anchor_rect")  # type: ignore[attr-defined]
                    anchor_rect = None
                    try:
                        if isinstance(anchor_val, (list, tuple)) and len(anchor_val) == 4:
                            anchor_rect = tuple(float(x) for x in anchor_val)
                        elif anchor_val is not None:
                            anchor_rect = (float(anchor_val.x0), float(anchor_val.y0), float(anchor_val.x1), float(anchor_val.y1))
                    except Exception:
                        anchor_rect = None
                    q = getattr(pl, "query", None)
                    if q is None:
                        q = pl.get("query")  # type: ignore[attr-defined]
                    exp = getattr(pl, "explanation", None)
                    if exp is None:
                        exp = pl.get("explanation")  # type: ignore[attr-defined]
                    try:
                        exp_override = state._NOTE_TEXT_OVERRIDES.get(str(uid))
                        if exp_override is not None:
                            exp = exp_override
                    except Exception:
                        pass
                    P = type("P", (), {})
                    p = P()
                    p.uid = uid
                    p.page_index = pg
                    p.query = q
                    p.explanation = exp
                    p.note_rect = rect_obj
                    p.anchor_rect = anchor_rect
                    frz.append(p)
                except Exception:
                    continue
        except Exception:
            frz = []

        queries = []
        comments = {}
        if manual:
            queries, comments = state._manual_queries_payload()

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
            freeze_placements=frz,
            fixed_note_rects=fixed,
            note_text_overrides=dict(state._NOTE_COLOR_OVERRIDES),
            note_fontsize_overrides=dict(state._NOTE_FONTSIZE_OVERRIDES),
            note_rotations=dict(state._ROTATION_OVERRIDES),
            rotate_text_with_box=True,
        )
    except Exception as exc:
        state._log("api:export_failed", type(exc).__name__, str(exc))
        try:
            os.unlink(tmp_pdf)
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"Export failed: {type(exc).__name__}: {exc}"}), 500

    name = secure_filename(request.args.get("name") or "annotated.pdf") or "annotated.pdf"

    @after_this_request
    def _cleanup(resp):
        try:
            os.unlink(tmp_pdf)
        except Exception:
            pass
        return resp

    return send_file(tmp_pdf, mimetype="application/pdf", as_attachment=True, download_name=name)


def _preview_meta() -> dict:
    """Build placements + page metadata (shared with web).

    Used by the interactive web overlay; this intentionally avoids baking a
    preview PDF (baking happens on export).
    """
    pdf_path = state._OCR_PDF or state._SRC_PDF
    ann = state._ANN_JSON
    manual = state._is_manual_mode()
    if not pdf_path or (not ann and not manual):
        return {"pages": [], "placements": [], "manual": manual}
    settings = state._resolved_settings()

    # Ensure plan + sizes exist (without generating a baked preview PDF).
    if manual:
        if state._PLACEMENTS is None:
            state._PLACEMENTS = []
    else:
        if state._PLACEMENTS is None:
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
                state._PLACEMENTS = placements
            except Exception:
                state._PLACEMENTS = []

    if not state._PAGE_SIZES:
        try:
            state._ensure_page_sizes(pdf_path)
        except Exception:
            pass

    default_fontsize = float(settings.get("note_fontsize", 9.0))
    fontsize_overrides = state._NOTE_FONTSIZE_OVERRIDES or {}
    rotation_overrides = state._ROTATION_OVERRIDES or {}
    ann_colors = {}
    if not manual:
        try:
            # Empty fallback lets us distinguish "no color provided" from "color provided".
            ann_colors = build_color_map(ann, fallback="")
        except Exception:
            pass
    color_overrides = state._NOTE_COLOR_OVERRIDES or {}
    text_overrides = state._NOTE_TEXT_OVERRIDES or {}
    default_note_text = str(settings.get("note_text") or "red").strip() or "red"
    default_highlight = "yellow"
    placements = []
    pls = state._PLACEMENTS or []
    fixed = state._FIXED_OVERRIDES

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
            return getattr(pl, attr)
        except Exception:
            pass
        try:
            return pl[key]
        except Exception:
            return None

    for pl in pls:
        try:
            uid = _get(pl, "uid", "uid")
            pg = _get(pl, "page_index", "page_index")
            rect = _get(pl, "note_rect", "note_rect")
            anchor = _get(pl, "anchor_rect", "anchor_rect")
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
            q = _get(pl, "query", "query")
            exp = _get(pl, "explanation", "explanation")
            try:
                if uid and uid in text_overrides:
                    exp = text_overrides.get(uid) or exp
            except Exception:
                pass
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
            placements.append(
                {
                    "uid": uid,
                    "page_index": pg,
                    "note_rect": rt,
                    "anchor_rect": at,
                    "query": q,
                    "explanation": exp,
                    "color": col,
                    "highlight_color": highlight_col,
                    "font_size": fsz,
                    "rotation": rot,
                }
            )
        except Exception:
            continue
    pages = [{"index": i, "width": w, "height": h} for i, (w, h) in (state._PAGE_SIZES or {}).items()]
    return {"pages": pages, "placements": placements, "manual": manual}


@app.get("/api/preview_meta")
def api_preview_meta():
    try:
        return jsonify(_preview_meta())
    except Exception as exc:
        state._log("api:preview_meta_failed", type(exc).__name__, str(exc))
        return jsonify({"pages": [], "placements": [], "manual": False})


@app.get("/api/preview_page_count")
def api_preview_page_count():
    try:
        pdf_path = state._OCR_PDF or state._SRC_PDF
        if not pdf_path:
            return jsonify({"count": 0, "pages": []})
        try:
            state._ensure_page_sizes(pdf_path)
        except Exception:
            pass
        sizes = state._PAGE_SIZES or {}
        pages = [{"index": i, "width": w, "height": h} for i, (w, h) in sizes.items()]
        return jsonify({"count": len(pages), "pages": pages})
    except Exception:
        return jsonify({"count": 0, "pages": []})


def _render_preview_page(index: int, max_width: int, max_height: int) -> dict:
    path = state._OCR_PDF or state._SRC_PDF
    if not path:
        raise RuntimeError("No source PDF available")
    try:
        fitz = _import_fitz()
        doc = fitz.open(path)
        if index < 0:
            index = 0
        if index >= len(doc):
            index = len(doc) - 1
        pg = doc[index]
        wpt = float(pg.rect.width)
        hpt = float(pg.rect.height)
        mw = max(200, int(max_width))
        mh = max(200, int(max_height))
        sx = mw / wpt
        sy = mh / hpt
        scale = max(0.2, min(sx if sx < sy else sy, 3.0))
        mat = fitz.Matrix(scale, scale)
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        data = pix.tobytes("png")
        doc.close()
    except Exception as exc:
        raise RuntimeError(f"Failed to rasterize page: {type(exc).__name__}: {exc}")
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "index": int(index),
        "data_url": "data:image/png;base64," + b64,
        "width_px": int(pix.width),
        "height_px": int(pix.height),
        "page_width_pts": float(wpt),
        "page_height_pts": float(hpt),
    }


@app.get("/api/render_preview_page")
def api_render_preview_page():
    try:
        page = int(request.args.get("page", "0"))
        max_w = int(request.args.get("w", "1400"))
        max_h = int(request.args.get("h", "900"))
    except Exception:
        page = 0
        max_w = 1400
        max_h = 900
    try:
        return jsonify(_render_preview_page(page, max_w, max_h))
    except Exception as exc:
        state._log("api:render_preview_page_failed", type(exc).__name__, str(exc))
        return jsonify({"error": str(exc)}), 400


def _set_note_rect(uid: str, x0: float, y0: float, x1: float, y1: float) -> bool:
    try:
        state._FIXED_OVERRIDES[str(uid)] = (float(x0), float(y0), float(x1), float(y1))
        state._log("set_note_rect", uid, (x0, y0, x1, y1))
        return True
    except Exception:
        return False


def _set_note_text(uid: str, text: str) -> bool:
    try:
        state._NOTE_TEXT_OVERRIDES[str(uid)] = str(text)
        state._log("set_note_text", uid, text[:120] + "..." if len(text) > 120 else text)
        return True
    except Exception:
        return False


def _set_note_color(uid: str, color: str) -> bool:
    try:
        state._NOTE_COLOR_OVERRIDES[str(uid)] = str(color)
        state._log("set_note_color", uid, color)
        return True
    except Exception:
        return False


def _set_note_fontsize(uid: str, size: float) -> bool:
    try:
        fs = float(size)
        if fs <= 0:
            return False
        state._NOTE_FONTSIZE_OVERRIDES[str(uid)] = fs
        state._log("set_note_fontsize", uid, fs)
        return True
    except Exception:
        return False


def _set_note_rotation(uid: str, angle: float) -> bool:
    try:
        state._ROTATION_OVERRIDES[str(uid)] = float(angle)
        state._log("set_note_rotation", uid, float(angle))
        return True
    except Exception:
        return False


@app.post("/api/set_note_rect")
def api_set_note_rect():
    payload = request.get_json(silent=True) or {}
    ok = _set_note_rect(payload.get("uid", ""), payload.get("x0", 0), payload.get("y0", 0), payload.get("x1", 0), payload.get("y1", 0))
    return jsonify({"ok": ok})


@app.post("/api/set_note_text")
def api_set_note_text():
    payload = request.get_json(silent=True) or {}
    ok = _set_note_text(payload.get("uid", ""), payload.get("text", ""))
    return jsonify({"ok": ok})


@app.post("/api/set_note_color")
def api_set_note_color():
    payload = request.get_json(silent=True) or {}
    ok = _set_note_color(payload.get("uid", ""), payload.get("color", ""))
    return jsonify({"ok": ok})


@app.post("/api/set_note_fontsize")
def api_set_note_fontsize():
    payload = request.get_json(silent=True) or {}
    ok = _set_note_fontsize(payload.get("uid", ""), payload.get("size", 0))
    return jsonify({"ok": ok})


@app.post("/api/set_note_rotation")
def api_set_note_rotation():
    payload = request.get_json(silent=True) or {}
    ok = _set_note_rotation(payload.get("uid", ""), payload.get("angle", 0))
    return jsonify({"ok": ok})


@app.post("/api/start_gemini")
def api_start_gemini():
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    model = (payload.get("model") or "gemini-2.5-flash").strip()
    max_items = int(payload.get("max_items") or 12)
    async_mode = str(request.args.get("async", "")).strip().lower() in ("1", "true", "yes")

    pdf_path = state._OCR_PDF or state._SRC_PDF
    if not pdf_path:
        return jsonify({"ok": False, "error": "Upload a PDF first."}), 400

    def _extract_pdf_text_to_temp(path: str) -> str | None:
        try:
            fitz = _import_fitz()
            doc = fitz.open(path)
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

    txt_path = _extract_pdf_text_to_temp(pdf_path)
    if not txt_path:
        return jsonify({"ok": False, "error": "Failed to extract text from PDF for Gemini."}), 500

    out_json = str(Path(pdf_path).with_suffix("")) + "__annotations.json"

    if async_mode:
        job_id = _job_create("gemini")
        _job_update(job_id, status="running")

        def _run():
            try:
                annotate_txt_file(
                    txt_path=txt_path,
                    objective=prompt,
                    outfile=out_json,
                    model=model or "gemini-2.5-flash",
                    max_items_hint=max_items,
                )
                state._ANN_JSON = out_json
                state._reset_annotation_state(manual=False)
                _job_update(job_id, status="done", next="/preview.html")
            except Exception as exc:
                state._log("api:gemini_failed", type(exc).__name__, str(exc))
                _job_update(job_id, status="error", error=f"Gemini failed: {type(exc).__name__}: {exc}")

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True, "job": job_id, "next": f"/loading_ai.html?job={job_id}"})

    try:
        annotate_txt_file(
            txt_path=txt_path,
            objective=prompt,
            outfile=out_json,
            model=model or "gemini-2.5-flash",
            max_items_hint=max_items,
        )
    except Exception as exc:
        state._log("api:gemini_failed", type(exc).__name__, str(exc))
        return jsonify({"ok": False, "error": f"Gemini failed: {type(exc).__name__}: {exc}"}), 500

    state._ANN_JSON = out_json
    state._reset_annotation_state(manual=False)
    return jsonify({"ok": True, "next": "/preview.html", "ann": out_json})


@app.get("/api/settings")
def api_get_settings():
    return jsonify(get_effective_settings())


@app.post("/api/settings")
def api_save_settings():
    payload = request.get_json(silent=True) or {}
    ok = save_user_settings(payload)
    return jsonify({"ok": bool(ok)})


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True})


@app.get("/api/note_font")
def api_note_font():
    """Serve the configured note font file for the web preview.

    This avoids relying on the browser being able to access local file paths.
    """
    settings = state._resolved_settings()
    fontfile = settings.get("note_fontfile")
    if not isinstance(fontfile, str) or not fontfile.strip():
        return ("Not Found", 404)
    p = Path(fontfile)
    if not p.exists():
        return ("Not Found", 404)
    ext = p.suffix.lower()
    allowed = {
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".ttc": "font/ttf",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }
    mimetype = allowed.get(ext)
    if not mimetype:
        return ("Not Found", 404)
    resp = send_file(str(p), mimetype=mimetype)
    try:
        resp.headers["Cache-Control"] = "no-store"
    except Exception:
        pass
    return resp


@app.route("/<path:filename>")
def serve_static(filename: str):
    target = WEB_ROOT / filename
    if target.exists():
        return send_from_directory(WEB_ROOT, filename)
    return send_from_directory(WEB_ROOT, "upload.html")


@app.route("/frontend/web/<path:filename>")
def serve_legacy_web_path(filename: str):
    # Allow older hardcoded links to continue working
    target = WEB_ROOT / filename
    if target.exists():
        return send_from_directory(WEB_ROOT, filename)
    # If the request was for upload.html under the legacy path, serve the new one
    if filename.endswith("upload.html"):
        return send_from_directory(WEB_ROOT, "upload.html")
    return ("Not Found", 404)


def _font_maker_cache_root() -> Path:
    try:
        FONT_MAKER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return FONT_MAKER_CACHE_DIR


def _purge_font_maker_cache(max_age_seconds: int = FONT_MAKER_CACHE_MAX_AGE_SECONDS) -> None:
    now = time.time()
    cache_root = _font_maker_cache_root()

    for token, meta in list(_FONT_MAKER_INDEX.items()):
        created = float(meta.get("created") or 0)
        p = Path(str(meta.get("path") or ""))
        if (now - created) > max_age_seconds or not p.exists():
            try:
                p.unlink()
            except Exception:
                pass
            _FONT_MAKER_INDEX.pop(token, None)

    try:
        for p in cache_root.glob("*.ttf"):
            try:
                if (now - p.stat().st_mtime) > max_age_seconds:
                    p.unlink()
            except Exception:
                continue
    except Exception:
        pass


@app.get("/custom_font_generator/font/<token>.ttf")
def font_maker_font_file(token: str):
    _purge_font_maker_cache()
    meta = _FONT_MAKER_INDEX.get(str(token))
    if not meta:
        p = _font_maker_cache_root() / f"{token}.ttf"
        if not p.exists():
            return ("Not Found", 404)
        meta = {"path": str(p), "name": p.name, "created": 0.0}

    p = Path(str(meta.get("path") or ""))
    if not p.exists():
        return ("Not Found", 404)
    resp = send_file(str(p), mimetype="font/ttf")
    try:
        resp.headers["Cache-Control"] = "no-store"
    except Exception:
        pass
    return resp


@app.get("/custom_font_generator/download/<token>")
def font_maker_download(token: str):
    _purge_font_maker_cache()
    meta = _FONT_MAKER_INDEX.get(str(token))
    if not meta:
        p = _font_maker_cache_root() / f"{token}.ttf"
        if not p.exists():
            return ("Not Found", 404)
        meta = {"path": str(p), "name": p.name, "created": 0.0}

    p = Path(str(meta.get("path") or ""))
    if not p.exists():
        return ("Not Found", 404)
    name = str(meta.get("name") or p.name or "handwriting.ttf")
    return send_file(str(p), mimetype="font/ttf", as_attachment=True, download_name=name)


@app.get("/custom_font_generator/meta/<token>")
def font_maker_meta(token: str):
    _purge_font_maker_cache()
    meta = _FONT_MAKER_INDEX.get(str(token))
    if not meta:
        p = _font_maker_cache_root() / f"{token}.ttf"
        if not p.exists():
            return jsonify({"ok": False, "error": "Not Found"}), 404
        return jsonify({"ok": True, "token": str(token), "name": p.name})

    p = Path(str(meta.get("path") or ""))
    if not p.exists():
        return jsonify({"ok": False, "error": "Not Found"}), 404
    name = str(meta.get("name") or p.name or "handwriting.ttf")
    return jsonify({"ok": True, "token": str(token), "name": name})


@app.get("/custom_font_generator/preview/<token>")
def font_maker_preview(token: str):
    _purge_font_maker_cache()
    meta = _FONT_MAKER_INDEX.get(str(token))
    if not meta:
        p = _font_maker_cache_root() / f"{token}.ttf"
        if not p.exists():
            return ("Not Found", 404)
        meta = {"path": str(p), "name": p.name, "created": 0.0}

    p = Path(str(meta.get("path") or ""))
    if not p.exists():
        return ("Not Found", 404)
    return redirect(f"/font_preview.html?token={token}")


@app.get("/custom_font_generator/static/handwrite_template.pdf")
def font_maker_template_pdf():
    p = (CUSTOM_FONT_ROOT / "static" / "handwrite_template.pdf").resolve()
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            resp = requests.get(_HANDWRITE_TEMPLATE_URL, timeout=30)
            resp.raise_for_status()
            p.write_bytes(resp.content)
        except Exception:
            return (
                "Template PDF is not available on the server.\n\n"
                "If you are deploying from git, ensure `custom_font_generator/static/handwrite_template.pdf` "
                "is committed (it may be ignored by `*.pdf` rules), or allow outbound network so the server can fetch it.",
                404,
            )
    if not p.exists():
        return ("Not Found", 404)
    return send_file(str(p), mimetype="application/pdf", as_attachment=True, download_name="handwrite_template.pdf")


@app.route("/custom_font_generator/<path:filename>")
def serve_font_generator(filename: str):
    target = CUSTOM_FONT_ROOT / filename
    if target.exists():
        return send_from_directory(CUSTOM_FONT_ROOT, filename)
    return ("Not Found", 404)


@app.post("/custom_font_generator/upload")
def font_maker_upload():
    file_obj = request.files.get("scan")
    if file_obj is None or not (file_obj.filename or "").strip():
        return ("No file uploaded", 400)

    _purge_font_maker_cache()

    scan_path = _save_upload(file_obj, "handwrite_scan")
    input_path = scan_path
    try:
        ext = (scan_path.suffix or "").lower()
        if ext == ".pdf" or (file_obj.mimetype or "").lower() == "application/pdf":
            fitz = _import_fitz()
            doc = fitz.open(str(scan_path))
            try:
                if getattr(doc, "page_count", 0) < 1:
                    return ("Uploaded PDF has no pages.", 400)
                pg = doc.load_page(0)
                scale = 4.0  # ~288 DPI for 72pt PDF units
                mat = fitz.Matrix(scale, scale)
                pix = pg.get_pixmap(matrix=mat, alpha=False)
                png_path = scan_path.with_suffix(".png")
                pix.save(str(png_path))
                input_path = png_path
            finally:
                try:
                    doc.close()
                except Exception:
                    pass
    except Exception as exc:
        return (f"Failed to prepare uploaded file: {type(exc).__name__}: {exc}", 400)

    out_dir = Path(tempfile.mkdtemp(prefix="anny_font_out_"))
    font_basename = secure_filename(Path(file_obj.filename).stem or scan_path.stem or "handwriting") or "handwriting"
    out_ttf = out_dir / f"{font_basename}.ttf"

    @after_this_request
    def _cleanup(resp):
        try:
            shutil.rmtree(scan_path.parent, ignore_errors=True)
        except Exception:
            pass
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass
        return resp

    cmd = [
        "handwrite",
        str(input_path),
        str(out_dir),
        "--filename",
        font_basename,
        "--family",
        font_basename,
        "--style",
        "Regular",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return (
            "Missing dependency: install the `handwrite` CLI (`pip install handwrite`) and FontForge, then restart Anny.",
            500,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        msg = f"Font generation failed (exit {exc.returncode})."
        if details:
            msg += "\n\n" + details
        return (msg, 500)

    if not out_ttf.exists():
        candidates = sorted(out_dir.glob("*.ttf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return ("Font generation finished, but no .ttf output was produced.", 500)
        out_ttf = candidates[0]

    token = uuid.uuid4().hex
    cache_root = _font_maker_cache_root()
    stored_ttf = cache_root / f"{token}.ttf"
    try:
        shutil.copy2(out_ttf, stored_ttf)
    except Exception as exc:
        return (f"Failed to store generated font: {type(exc).__name__}: {exc}", 500)

    _FONT_MAKER_INDEX[str(token)] = {"path": str(stored_ttf), "name": out_ttf.name, "created": time.time()}
    return redirect(f"/custom_font_generator/preview/{token}")


@app.route("/fonts/<path:filename>")
def serve_fonts(filename: str):
    target = FONTS_ROOT / filename
    if target.exists():
        return send_from_directory(FONTS_ROOT, filename)
    return ("Not Found", 404)


@app.get("/font-maker")
def font_maker_index():
    page = CUSTOM_FONT_ROOT / "font_page.html"
    if page.exists():
        return send_from_directory(CUSTOM_FONT_ROOT, "font_page.html")
    return ("Not Found", 404)


if __name__ == "__main__":
    # Flask dev server for running the app as a web experience.
    port = int(os.environ.get("PORT", "5001"))
    debug = str(os.environ.get("FLASK_DEBUG", "")).strip().lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
