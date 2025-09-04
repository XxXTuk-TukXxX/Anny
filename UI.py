# annotate_suite.py
# One UI to: (1) OCR a PDF, (2) configure annotation settings, (3) exact preview & export.
# Requires:
#   pip install ocrmypdf pymupdf
# External:
#   Tesseract OCR installed (or pick its path in Step 1).
#
# Files expected alongside this script:
#   - highlights.py   (contains highlight_and_margin_comment_pdf with plan_only & fixed_note_rects)

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, Tuple, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- BACKEND (OCR) ---
import ocrmypdf


def ensure_tesseract_available(custom_tesseract_path: str | None = None) -> None:
    if custom_tesseract_path:
        p = Path(custom_tesseract_path)
        if not p.exists():
            raise FileNotFoundError(f"Tesseract not found at: {custom_tesseract_path}")
        os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract is not available on PATH.\n\n"
            "Install Tesseract (e.g., UB Mannheim build on Windows) or pick its path "
            "in the 'Tesseract path' field."
        )


def _remove_background_supported() -> bool:
    # OCRmyPDF disabled --remove-background in v13+
    try:
        major = int(str(ocrmypdf.__version__).split(".")[0])
        return major < 13
    except Exception:
        return False


def run_ocr(
    input_pdf: str,
    output_pdf: str | None = None,
    languages: str = "eng",
    force: bool = False,
    jobs: int | None = None,
    optimize: int = 0,
    deskew: bool = True,
    clean: bool = False,
    custom_tesseract_path: str | None = None,
) -> Path:
    ensure_tesseract_available(custom_tesseract_path)
    in_path = Path(input_pdf)
    if not in_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {in_path}")
    out_path = Path(output_pdf) if output_pdf else in_path.with_suffix(".ocr.pdf")

    use_clean = bool(clean and _remove_background_supported())
    try:
        ocrmypdf.ocr(
            input_file=str(in_path),
            output_file=str(out_path),
            language=languages,
            force_ocr=force,
            skip_text=not force,
            rotate_pages=True,
            rotate_pages_threshold=14.0,
            deskew=deskew,
            remove_background=use_clean,
            optimize=optimize,
            jobs=jobs,
            progress_bar=False,
        )
    except NotImplementedError:
        # Fallback if user toggled "clean" on an unsupported version
        ocrmypdf.ocr(
            input_file=str(in_path),
            output_file=str(out_path),
            language=languages,
            force_ocr=force,
            skip_text=not force,
            rotate_pages=True,
            rotate_pages_threshold=14.0,
            deskew=deskew,
            remove_background=False,
            optimize=optimize,
            jobs=jobs,
            progress_bar=False,
        )

    return out_path


# --- IMPORT YOUR HIGHLIGHTER ---
try:
    from highlights import highlight_and_margin_comment_pdf  # your function
    from highlights import _import_fitz  # same PyMuPDF loader
except Exception as e:
    raise SystemExit(
        "Could not import 'highlight_and_margin_comment_pdf' from highlights.py.\n"
        "Make sure highlights.py is in the same folder and includes the updated function.\n"
        f"Import error: {e}"
    )


# --- HELPERS: JSON color map for UI rectangle outlines ---
def _tk_color(s: Optional[str], default: str = "#ff9800") -> str:
    if not s:
        return default
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        return s
    return s  # allow 'yellow', 'red', etc.


def build_color_map(annotations_json_path: str, fallback: str = "#ff9800") -> Dict[str, str]:
    p = Path(annotations_json_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    cmap: Dict[str, str] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        q = (row.get("quote") or row.get("query") or "").strip()
        if q:
            cmap[q] = _tk_color(row.get("color"), fallback)
    return cmap


# --- DEFAULTS (your block) ---
DEFAULTS = {
    "note_width": 240,
    "min_note_width": 48,
    "note_fontsize": 9.0,
    "note_fill": "",  # empty string -> None
    "note_border": "",
    "note_border_width": 0,
    "note_text": "red",
    "draw_leader": False,
    "leader_color": "",
    "allow_column_footer": True,
    "column_footer_max_offset": 250,
    "max_vertical_offset": 90,
    "max_scan": 420,
    "side": "outer",
    "allow_center_gutter": True,
    "center_gutter_tolerance": 48.0,
    "dedupe_scope": "page",
    "note_fontname": "PatrickHand",
    "note_fontfile": r".\fonts\PatrickHand-Regular.ttf",
}

SCALE = 1.5
# Default off: rebuilding the full PDF on every drag makes the UI feel choppy
# and can also cause the layout engine to re-evaluate placements. Users can
# still click the "Refresh preview" button to rebuild when ready.
AUTO_REFRESH_AFTER_DRAG = False


class WizardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF OCR → Annotate → Preview/Export (Exact)")
        self.geometry("1200x900")

        # State shared across steps
        self.src_pdf: Optional[str] = None  # original PDF chosen
        self.ocr_pdf: Optional[str] = None  # OCR output (if run)
        self.ann_json: Optional[str] = None  # annotations JSON
        self.fixed_overrides: Dict[str, Tuple[float, float, float, float]] = {}  # uid -> rect
        self.placements = []  # plan-only placements
        self.color_map: Dict[str, str] = {}

        # Preview doc state (temp annotated PDF)
        self._preview_pdf_path: Optional[str] = None
        self.doc = None
        self.page_imgs_ppm: Dict[int, bytes] = {}
        self.page_sizes: Dict[int, Tuple[int, int]] = {}
        self.cur_page = 0

        self.fitz = _import_fitz()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    # ---------- UI scaffold ----------
    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.step1 = ttk.Frame(self.nb)
        self.step2 = ttk.Frame(self.nb)
        self.step3 = ttk.Frame(self.nb)

        self.nb.add(self.step1, text="1) OCR PDF")
        self.nb.add(self.step2, text="2) Annotation Settings")
        self.nb.add(self.step3, text="3) Preview (Exact) & Export")

        self._build_step1()
        self._build_step2()
        self._build_step3()

    # ---------- STEP 1: OCR ----------
    def _build_step1(self):
        pad = {"padx": 8, "pady": 6}

        tk.Label(self.step1, text="Input PDF:").grid(row=0, column=0, sticky="e", **pad)
        self.in_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.in_var, width=70).grid(row=0, column=1, **pad)
        ttk.Button(self.step1, text="Browse...", command=self._browse_in_pdf).grid(row=0, column=2, **pad)

        tk.Label(self.step1, text="OCR Output PDF:").grid(row=1, column=0, sticky="e", **pad)
        self.out_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.out_var, width=70).grid(row=1, column=1, **pad)
        ttk.Button(self.step1, text="Save As...", command=self._browse_out_pdf).grid(row=1, column=2, **pad)

        tk.Label(self.step1, text="Languages:").grid(row=2, column=0, sticky="e", **pad)
        self.lang_var = tk.StringVar(value="eng")
        tk.Entry(self.step1, textvariable=self.lang_var, width=20).grid(row=2, column=1, sticky="w", **pad)

        self.force_var = tk.BooleanVar(value=False)
        self.deskew_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=_remove_background_supported())
        self.optimize_var = tk.IntVar(value=0)

        ttk.Checkbutton(self.step1, text="Force OCR (re-OCR pages with text)", variable=self.force_var)\
            .grid(row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(self.step1, text="Deskew", variable=self.deskew_var)\
            .grid(row=4, column=1, sticky="w", **pad)
        self.clean_chk = ttk.Checkbutton(self.step1, text="Clean background", variable=self.clean_var)
        self.clean_chk.grid(row=5, column=1, sticky="w", **pad)
        if not _remove_background_supported():
            self.clean_var.set(False)
            self.clean_chk.state(["disabled"])
            ttk.Label(self.step1, text="(not supported by your OCRmyPDF version)", foreground="gray")\
                .grid(row=5, column=2, sticky="w", **pad)

        tk.Label(self.step1, text="Optimize (0–3):").grid(row=6, column=0, sticky="e", **pad)
        tk.Spinbox(self.step1, from_=0, to=3, textvariable=self.optimize_var, width=5)\
            .grid(row=6, column=1, sticky="w", **pad)

        tk.Label(self.step1, text="Tesseract path (optional):").grid(row=7, column=0, sticky="e", **pad)
        self.tess_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.tess_var, width=70).grid(row=7, column=1, **pad)
        ttk.Button(self.step1, text="Find...", command=self._browse_tesseract).grid(row=7, column=2, **pad)

        self.ocr_status = tk.StringVar(value="Idle")
        tk.Label(self.step1, textvariable=self.ocr_status, fg="gray").grid(row=8, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 6))
        self.ocr_prog = ttk.Progressbar(self.step1, mode="indeterminate")
        self.ocr_prog.grid(row=9, column=0, columnspan=3, sticky="we", padx=12, pady=(0, 12))

        bar = ttk.Frame(self.step1)
        bar.grid(row=10, column=0, columnspan=3, sticky="e", padx=12, pady=(4, 12))
        ttk.Button(bar, text="Run OCR", command=self._run_ocr_clicked).pack(side="left", padx=6)
        ttk.Button(bar, text="Skip OCR → Next", command=lambda: self.nb.select(self.step2)).pack(side="left", padx=6)

    def _browse_in_pdf(self):
        p = filedialog.askopenfilename(title="Choose input PDF", filetypes=[("PDF files", "*.pdf")])
        if p:
            self.in_var.set(p)
            self.src_pdf = p
            if not self.out_var.get():
                self.out_var.set(str(Path(p).with_suffix(".ocr.pdf")))

    def _browse_out_pdf(self):
        p = filedialog.asksaveasfilename(
            title="Save OCR'd PDF as...",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if p:
            self.out_var.set(p)

    def _browse_tesseract(self):
        p = filedialog.askopenfilename(
            title="Locate Tesseract executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if p:
            self.tess_var.set(p)

    def _run_ocr_clicked(self):
        if not self.in_var.get().strip():
            messagebox.showwarning("Missing file", "Please choose an input PDF.")
            return

        self.ocr_status.set("Running OCR…")
        self.ocr_prog.start(10)

        def worker():
            try:
                outp = run_ocr(
                    input_pdf=self.in_var.get().strip(),
                    output_pdf=(self.out_var.get().strip() or None),
                    languages=(self.lang_var.get().strip() or "eng"),
                    force=self.force_var.get(),
                    optimize=int(self.optimize_var.get()),
                    deskew=self.deskew_var.get(),
                    clean=self.clean_var.get(),
                    custom_tesseract_path=(self.tess_var.get().strip() or None),
                )
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                self.after(0, lambda m=err_msg: self._ocr_done(error=m))
                return
            self.after(0, lambda p=str(outp): self._ocr_done(result=p))

        threading.Thread(target=worker, daemon=True).start()

    def _ocr_done(self, result: Optional[str] = None, error: Optional[str] = None):
        self.ocr_prog.stop()
        if error:
            self.ocr_status.set("Error")
            messagebox.showerror("OCR failed", error)
            return
        self.ocr_status.set("Done")
        self.ocr_pdf = result
        self.src_pdf = self.src_pdf or result
        messagebox.showinfo("Success", f"OCR complete:\n{result}\n\nProceed to Step 2.")
        self.nb.select(self.step2)

    # ---------- STEP 2: Settings ----------
    def _build_step2(self):
        pad = {"padx": 8, "pady": 4}
        row = 0

        tk.Label(self.step2, text="Annotations JSON:").grid(row=row, column=0, sticky="e", **pad)
        self.json_var = tk.StringVar()
        tk.Entry(self.step2, textvariable=self.json_var, width=80).grid(row=row, column=1, **pad)
        ttk.Button(self.step2, text="Browse...", command=self._browse_json).grid(row=row, column=2, **pad)
        row += 1

        # Font controls
        tk.Label(self.step2, text="Font name:").grid(row=row, column=0, sticky="e", **pad)
        self.fontname_var = tk.StringVar(value=DEFAULTS["note_fontname"])
        tk.Entry(self.step2, textvariable=self.fontname_var, width=24).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        tk.Label(self.step2, text="Font file (TTF/OTF):").grid(row=row, column=0, sticky="e", **pad)
        self.fontfile_var = tk.StringVar(value=DEFAULTS["note_fontfile"])
        tk.Entry(self.step2, textvariable=self.fontfile_var, width=80).grid(row=row, column=1, **pad)
        ttk.Button(self.step2, text="Browse...", command=self._browse_font).grid(row=row, column=2, **pad)
        row += 1

        # Numeric settings
        self.note_width_var = tk.IntVar(value=DEFAULTS["note_width"])
        self.min_width_var = tk.IntVar(value=DEFAULTS["min_note_width"])
        self.fontsize_var = tk.DoubleVar(value=DEFAULTS["note_fontsize"])
        self.col_footer_var = tk.BooleanVar(value=DEFAULTS["allow_column_footer"])
        self.col_footer_max_var = tk.IntVar(value=DEFAULTS["column_footer_max_offset"])
        self.max_vert_var = tk.IntVar(value=DEFAULTS["max_vertical_offset"])
        self.max_scan_var = tk.IntVar(value=DEFAULTS["max_scan"])
        self.center_gutter_var = tk.BooleanVar(value=DEFAULTS["allow_center_gutter"])
        self.center_tol_var = tk.DoubleVar(value=DEFAULTS["center_gutter_tolerance"])

        f = ttk.LabelFrame(self.step2, text="Dimensions")
        f.grid(row=row, column=0, columnspan=3, sticky="we", padx=8, pady=8)
        ttk.Label(f, text="Note width").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(f, textvariable=self.note_width_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="Min width").grid(row=0, column=2, sticky="e", padx=6)
        ttk.Entry(f, textvariable=self.min_width_var, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(f, text="Font size").grid(row=0, column=4, sticky="e", padx=6)
        ttk.Entry(f, textvariable=self.fontsize_var, width=8).grid(row=0, column=5, sticky="w")

        f2 = ttk.LabelFrame(self.step2, text="Placement")
        f2.grid(row=row + 1, column=0, columnspan=3, sticky="we", padx=8, pady=8)
        ttk.Checkbutton(f2, text="Allow column footer", variable=self.col_footer_var).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(f2, text="Footer max offset").grid(row=0, column=1, sticky="e")
        ttk.Entry(f2, textvariable=self.col_footer_max_var, width=8).grid(row=0, column=2, sticky="w")
        ttk.Label(f2, text="Max vertical offset").grid(row=0, column=3, sticky="e", padx=6)
        ttk.Entry(f2, textvariable=self.max_vert_var, width=8).grid(row=0, column=4, sticky="w")
        ttk.Label(f2, text="Max scan").grid(row=0, column=5, sticky="e", padx=6)
        ttk.Entry(f2, textvariable=self.max_scan_var, width=8).grid(row=0, column=6, sticky="w")

        ttk.Label(f2, text="Side").grid(row=1, column=0, sticky="e", padx=6)
        self.side_var = tk.StringVar(value=DEFAULTS["side"])
        ttk.Combobox(
            f2,
            textvariable=self.side_var,
            values=["nearest", "left", "right", "outer", "inner"],
            width=10,
            state="readonly",
        ).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(f2, text="Allow center gutter", variable=self.center_gutter_var).grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(f2, text="Center tolerance").grid(row=1, column=3, sticky="e")
        ttk.Entry(f2, textvariable=self.center_tol_var, width=8).grid(row=1, column=4, sticky="w")

        # Colors + leader
        self.note_fill_var = tk.StringVar(value=DEFAULTS["note_fill"])
        self.note_border_var = tk.StringVar(value=DEFAULTS["note_border"])
        self.note_border_width_var = tk.IntVar(value=DEFAULTS["note_border_width"])
        self.note_text_var = tk.StringVar(value=DEFAULTS["note_text"])
        self.draw_leader_var = tk.BooleanVar(value=DEFAULTS["draw_leader"])
        self.leader_color_var = tk.StringVar(value=DEFAULTS["leader_color"])

        f3 = ttk.LabelFrame(self.step2, text="Visuals")
        f3.grid(row=row + 2, column=0, columnspan=3, sticky="we", padx=8, pady=8)
        ttk.Label(f3, text="Note fill (empty=None)").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(f3, textvariable=self.note_fill_var, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(f3, text="Border (empty=None)").grid(row=0, column=2, sticky="e", padx=6)
        ttk.Entry(f3, textvariable=self.note_border_var, width=14).grid(row=0, column=3, sticky="w")
        ttk.Label(f3, text="Border width").grid(row=0, column=4, sticky="e", padx=6)
        ttk.Entry(f3, textvariable=self.note_border_width_var, width=8).grid(row=0, column=5, sticky="w")
        ttk.Label(f3, text="Text color").grid(row=1, column=0, sticky="e", padx=6)
        ttk.Entry(f3, textvariable=self.note_text_var, width=14).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(f3, text="Draw leader", variable=self.draw_leader_var).grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(f3, text="Leader color (empty=None)").grid(row=1, column=3, sticky="e")
        ttk.Entry(f3, textvariable=self.leader_color_var, width=14).grid(row=1, column=4, sticky="w")

        bar = ttk.Frame(self.step2)
        bar.grid(row=row + 3, column=0, columnspan=3, sticky="e", padx=12, pady=12)
        ttk.Button(bar, text="Compute Preview", command=self._compute_preview_clicked).pack(side="left", padx=6)
        ttk.Button(bar, text="Next → Preview", command=lambda: self.nb.select(self.step3)).pack(side="left", padx=6)

    def _browse_json(self):
        p = filedialog.askopenfilename(title="Choose annotations JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if p:
            self.json_var.set(p)
            self.ann_json = p

    def _browse_font(self):
        p = filedialog.askopenfilename(title="Choose TTF/OTF font file", filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")])
        if p:
            self.fontfile_var.set(p)

    def _gather_settings(self):
        def none_if_empty(s: str | None):
            s = (s or "").strip()
            return None if s == "" else s

        return dict(
            note_width=int(self.note_width_var.get()),
            min_note_width=int(self.min_width_var.get()),
            note_fontsize=float(self.fontsize_var.get()),
            note_fill=none_if_empty(self.note_fill_var.get()),
            note_border=none_if_empty(self.note_border_var.get()),
            note_border_width=int(self.note_border_width_var.get()),
            note_text=self.note_text_var.get().strip() or "red",
            draw_leader=bool(self.draw_leader_var.get()),
            leader_color=none_if_empty(self.leader_color_var.get()),
            allow_column_footer=bool(self.col_footer_var.get()),
            column_footer_max_offset=int(self.col_footer_max_var.get()),
            max_vertical_offset=int(self.max_vert_var.get()),
            max_scan=int(self.max_scan_var.get()),
            side=self.side_var.get(),
            allow_center_gutter=bool(self.center_gutter_var.get()),
            center_gutter_tolerance=float(self.center_tol_var.get()),
            dedupe_scope="page",
            note_fontname=self.fontname_var.get().strip() or "PatrickHand",
            note_fontfile=self.fontfile_var.get().strip() or None,
        )

    def _compute_preview_clicked(self):
        if not (self.ocr_pdf or self.src_pdf):
            messagebox.showwarning("No PDF", "Choose or generate a PDF in Step 1.")
            return
        if not self.json_var.get().strip():
            messagebox.showwarning("No JSON", "Choose annotations JSON.")
            return

        pdf_path = self.ocr_pdf or self.src_pdf
        self.ann_json = self.json_var.get().strip()
        self.color_map = build_color_map(self.ann_json, fallback="#ff9800")
        settings = self._gather_settings()

        try:
            _, hits, notes, skipped, placements = highlight_and_margin_comment_pdf(
                pdf_path=pdf_path,
                queries=[],
                comments={},
                annotations_json=self.ann_json,
                plan_only=True,
                **settings,
            )
        except Exception as e:
            messagebox.showerror("Preview failed", f"{type(e).__name__}: {e}")
            return

        self.placements = placements
        self.fixed_overrides = {}  # reset

        # Build exact preview PDF and rasterize it
        self._build_exact_preview_pdf()
        self.cur_page = 0
        self._draw_page()
        self.nb.select(self.step3)
        messagebox.showinfo("Preview ready", f"Found {hits} highlights, {notes} notes (skipped {skipped}).")

    # ---------- STEP 3: Preview/Export ----------
    def _build_step3(self):
        # Toolbar
        tb = ttk.Frame(self.step3)
        tb.pack(side="top", fill="x")
        ttk.Button(tb, text="◀ Prev page", command=self._prev_page).pack(side="left", padx=4, pady=6)
        ttk.Button(tb, text="Next page ▶", command=self._next_page).pack(side="left", padx=4, pady=6)

        ttk.Button(tb, text="Refresh preview", command=self._refresh_preview).pack(side="left", padx=12)
        # Preview behavior toggles
        self.freeze_all_var = tk.BooleanVar(value=True)
        self.auto_refresh_var = tk.BooleanVar(value=AUTO_REFRESH_AFTER_DRAG)
        ttk.Checkbutton(tb, text="Freeze layout", variable=self.freeze_all_var).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(tb, text="Auto-refresh after drag", variable=self.auto_refresh_var).pack(side="left", padx=(8, 0))

        ttk.Label(tb, text="Export to:").pack(side="left", padx=(24, 6))
        self.export_var = tk.StringVar(value="annotated.pdf")
        ttk.Entry(tb, textvariable=self.export_var, width=40).pack(side="left", padx=4)
        ttk.Button(tb, text="Browse...", command=self._browse_export).pack(side="left", padx=4)
        ttk.Button(tb, text="Export PDF", command=self._export_clicked).pack(side="right", padx=8)

        # Scrollable canvas
        outer = ttk.Frame(self.step3)
        outer.pack(side="top", fill="both", expand=True)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, bg="#222", highlightthickness=0)
        self.vsb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(outer, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")

        # Dragging bindings
        self.canvas.bind("<Button-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        # Scroll wheel
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

        self._drag_uid = None
        self._drag_dx = 0
        self._drag_dy = 0

    # ---------- Preview building / drawing ----------
    def _planned_rect_map(self) -> Dict[str, Tuple[float, float, float, float]]:
        return {p.uid: p.note_rect for p in self.placements}

    def _build_exact_preview_pdf(self):
        """Render a temporary annotated PDF (identical to export), then rasterize."""
        if not (self.ocr_pdf or self.src_pdf):
            return
        pdf_path = self.ocr_pdf or self.src_pdf
        settings = self._gather_settings()

        planned = self._planned_rect_map()
        # Freeze all notes by default: pass all planned rects as fixed
        if getattr(self, "freeze_all_var", None) is not None and self.freeze_all_var.get():
            combined = {**planned, **self.fixed_overrides}
        else:
            # Only force edited ones; let untouched notes auto-place
            combined = {**self.fixed_overrides}

        # temp file
        fd, tmp = tempfile.mkstemp(suffix="_annot_preview.pdf")
        os.close(fd)
        self._preview_pdf_path = tmp

        # draw real PDF using the same engine/path as export
        highlight_and_margin_comment_pdf(
            pdf_path=pdf_path,
            queries=[],
            comments={},
            annotations_json=self.ann_json,
            out_path=tmp,
            fixed_note_rects=combined,
            freeze_placements=(self.placements if getattr(self, "freeze_all_var", None) is not None and self.freeze_all_var.get() else None),
            **settings,
        )

        # open and rasterize
        self._open_doc(tmp)
        self._rasterize_pages()
        self.cur_page = max(0, min(self.cur_page, len(self.page_imgs_ppm) - 1))

    def _open_doc(self, pdf_path: str):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = self.fitz.open(pdf_path)

    def _rasterize_pages(self):
        self.page_imgs_ppm.clear()
        self.page_sizes.clear()
        mat = self.fitz.Matrix(SCALE, SCALE)
        for i, page in enumerate(self.doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            self.page_imgs_ppm[i] = pix.tobytes("ppm")
            self.page_sizes[i] = (pix.width, pix.height)

    def _draw_page(self):
        self.canvas.delete("all")
        w, h = self.page_sizes[self.cur_page]
        photo = tk.PhotoImage(data=self.page_imgs_ppm[self.cur_page])
        self._photo = photo  # keep a ref
        self.canvas.create_image(0, 0, anchor="nw", image=photo, tags=("pageimg",))
        self.canvas.config(scrollregion=(0, 0, w, h), width=min(w, 1200), height=min(h, 900))

        # overlay simple draggable boxes (no Tk text; PDF already has real note text)
        for pl in [p for p in self.placements if p.page_index == self.cur_page]:
            x0, y0, x1, y1 = self.fixed_overrides.get(pl.uid, pl.note_rect)
            col = self.color_map.get(pl.query, "#ff9800")
            cx0, cy0, cx1, cy1 = x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE
            # tag with a stable uid prefix so hit-testing is robust
            self.canvas.create_rectangle(
                cx0, cy0, cx1, cy1,
                outline=col, width=2, fill="",
                tags=("note", f"uid:{pl.uid}")
            )

    # ---------- paging ----------
    def _prev_page(self):
        self.cur_page = (self.cur_page - 1) % len(self.page_imgs_ppm)
        self._draw_page()

    def _next_page(self):
        self.cur_page = (self.cur_page + 1) % len(self.page_imgs_ppm)
        self._draw_page()

    def _browse_export(self):
        p = filedialog.asksaveasfilename(
            title="Export annotated PDF as...",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if p:
            self.export_var.set(p)

    # ---------- dragging ----------
    def _find_uid_at(self, x, y) -> Optional[str]:
        """Return uid for the topmost note whose rectangle contains (x,y).
        Falls back to a small overlap tolerance for border clicks.
        Coordinates must be canvas-space (use canvasx/canvasy).
        """
        # Prefer interior hit: check all note rectangles whose bbox contains the point
        note_items = list(self.canvas.find_withtag("note"))
        containing = []
        for obj in note_items:
            coords = self.canvas.coords(obj)
            if not coords or len(coords) < 4:
                continue
            x0, y0, x1, y1 = coords[:4]
            if x0 <= x <= x1 and y0 <= y <= y1:
                containing.append(obj)

        if containing:
            # pick topmost among containing
            for obj in reversed(self.canvas.find_all()):
                if obj in containing:
                    for t in self.canvas.gettags(obj):
                        if t.startswith("uid:"):
                            return t[4:]
            # fallback just in case tags missing
            obj = containing[-1]
            for t in self.canvas.gettags(obj):
                if t.startswith("uid:"):
                    return t[4:]

        # Fallback: small tolerance around pointer to catch border-only clicks
        tol = 4
        hits = self.canvas.find_overlapping(x - tol, y - tol, x + tol, y + tol)
        for obj in reversed(hits):  # topmost first
            for t in self.canvas.gettags(obj):
                if t.startswith("uid:"):
                    return t[4:]
        return None

    def _rect_for_uid_canvas(self, uid):
        for obj in self.canvas.find_withtag(f"uid:{uid}"):
            if "note" in self.canvas.gettags(obj):
                return self.canvas.coords(obj)  # [x0,y0,x1,y1]
        return None

    def _move_uid(self, uid, x0, y0, x1, y1):
        for obj in self.canvas.find_withtag(f"uid:{uid}"):
            if "note" in self.canvas.gettags(obj):
                self.canvas.coords(obj, x0, y0, x1, y1)

    def _on_down(self, e):
        # Convert to canvas coordinates to respect scrolling
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        uid = self._find_uid_at(cx, cy)
        if not uid:
            return
        self._drag_uid = uid
        rect = self._rect_for_uid_canvas(uid)
        if rect:
            x0, y0, x1, y1 = rect
            self._drag_dx = cx - x0
            self._drag_dy = cy - y0

    def _on_drag(self, e):
        if not self._drag_uid:
            return
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        x0 = cx - self._drag_dx
        y0 = cy - self._drag_dy
        rect = self._rect_for_uid_canvas(self._drag_uid)
        if not rect:
            return
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        self._move_uid(self._drag_uid, x0, y0, x0 + w, y0 + h)

    def _on_up(self, e):
        if not self._drag_uid:
            return
        rect = self._rect_for_uid_canvas(self._drag_uid)
        if rect:
            x0, y0, x1, y1 = rect
            self.fixed_overrides[self._drag_uid] = (x0 / SCALE, y0 / SCALE, x1 / SCALE, y1 / SCALE)
        self._drag_uid = None
        # Respect UI toggle; default off for smoother interactions
        try:
            do_auto = bool(self.auto_refresh_var.get())
        except Exception:
            do_auto = bool(AUTO_REFRESH_AFTER_DRAG)
        if do_auto:
            self._refresh_preview()

    def _on_mousewheel(self, event):
        delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")

    def _refresh_preview(self):
        self._build_exact_preview_pdf()
        self._draw_page()

    # ---------- export ----------
    def _export_clicked(self):
        if not self.export_var.get().strip():
            messagebox.showwarning("Missing path", "Choose an export filename.")
            return
        if not (self.ocr_pdf or self.src_pdf):
            messagebox.showwarning("No PDF", "There is no PDF to export.")
            return
        if not self.ann_json:
            messagebox.showwarning("No JSON", "Choose annotations JSON in Step 2.")
            return

        pdf_path = self.ocr_pdf or self.src_pdf
        settings = self._gather_settings()
        planned = self._planned_rect_map()
        if getattr(self, "freeze_all_var", None) is not None and self.freeze_all_var.get():
            combined = {**planned, **self.fixed_overrides}
        else:
            combined = {**self.fixed_overrides}

        try:
            out, hi, no, sk = highlight_and_margin_comment_pdf(
                pdf_path=pdf_path,
                queries=[],
                comments={},
                annotations_json=self.ann_json,
                out_path=self.export_var.get().strip(),
                fixed_note_rects=combined,
                freeze_placements=(self.placements if getattr(self, "freeze_all_var", None) is not None and self.freeze_all_var.get() else None),
                **settings,
            )
        except Exception as e:
            messagebox.showerror("Export failed", f"{type(e).__name__}: {e}")
            return

        messagebox.showinfo("Done", f"Saved: {out}\nHighlights={hi}  Notes={no}  Skipped={sk}")

    # ---------- cleanup ----------
    def _on_close(self):
        try:
            if self.doc is not None:
                self.doc.close()
        except Exception:
            pass
        if self._preview_pdf_path and os.path.exists(self._preview_pdf_path):
            try:
                os.remove(self._preview_pdf_path)
            except Exception:
                pass
        self.destroy()


def main():
    app = WizardApp()
    app.mainloop()


if __name__ == "__main__":
    main()
