import json
import os
from pathlib import Path
import tempfile
from typing import Dict, Tuple, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from highlights import highlight_and_margin_comment_pdf
from .colors import build_color_map
from .defaults import DEFAULTS

# Optional Gemini integration
_GEMINI_AVAILABLE = True
_GEMINI_IMPORT_ERR = None
try:
    from models.gemini_annotaton import annotate_txt_file as gemini_annotate
except Exception as _e:  # pragma: no cover - optional dependency
    _GEMINI_AVAILABLE = False
    _GEMINI_IMPORT_ERR = str(_e)


class Step2Mixin:
        # ---------- STEP 2: Settings ----------
        def _build_step2(self):
            pad = {"padx": 8, "pady": 4}
            row = 0
    
            # Source chooser
            srcf = ttk.Frame(self.step2)
            srcf.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))
            ttk.Label(srcf, text="Annotation source:").pack(side="left")
            ttk.Radiobutton(srcf, text="JSON file", value="json", variable=self.ann_source_var,
                            command=self._update_ann_source_ui).pack(side="left", padx=(8, 0))
            ttk.Radiobutton(srcf, text="Gemini AI", value="gemini", variable=self.ann_source_var,
                            command=self._update_ann_source_ui).pack(side="left", padx=(8, 0))
            if not _GEMINI_AVAILABLE:
                ttk.Label(srcf, text="(Gemini unavailable: install google-genai, set GOOGLE_API_KEY)", foreground="gray").pack(side="left", padx=(12, 0))
            row += 1
    
            # JSON source panel
            self.json_panel = ttk.Frame(self.step2)
            self.json_panel.grid(row=row, column=0, columnspan=3, sticky="we")
            tk.Label(self.json_panel, text="Annotations JSON:").grid(row=0, column=0, sticky="e", **pad)
            self.json_var = tk.StringVar()
            tk.Entry(self.json_panel, textvariable=self.json_var, width=80).grid(row=0, column=1, **pad)
            ttk.Button(self.json_panel, text="Browse...", command=self._browse_json).grid(row=0, column=2, **pad)
    
            # Gemini source panel
            self.gemini_panel = ttk.LabelFrame(self.step2, text="Gemini annotator")
            self.gemini_panel.grid(row=row, column=0, columnspan=3, sticky="we", padx=8)
            # No TXT selection; extraction happens automatically from current PDF
            ttk.Label(self.gemini_panel, text="Objective:").grid(row=0, column=0, sticky="e", **pad)
            tk.Entry(self.gemini_panel, textvariable=self.g_objective_var, width=70).grid(row=0, column=1, columnspan=2, sticky="w", **pad)
            # Model & count
            ttk.Label(self.gemini_panel, text="Model:").grid(row=1, column=0, sticky="e", **pad)
            tk.Entry(self.gemini_panel, textvariable=self.g_model_var, width=28).grid(row=1, column=1, sticky="w", **pad)
            ttk.Label(self.gemini_panel, text="Max items:").grid(row=1, column=2, sticky="e", **pad)
            tk.Spinbox(self.gemini_panel, from_=1, to=50, textvariable=self.g_max_items_var, width=6).grid(row=1, column=3, sticky="w", **pad)
            # Output JSON
            ttk.Label(self.gemini_panel, text="Output annotations JSON:").grid(row=2, column=0, sticky="e", **pad)
            tk.Entry(self.gemini_panel, textvariable=self.g_outfile_var, width=70).grid(row=2, column=1, **pad)
            ttk.Button(self.gemini_panel, text="Save As...", command=self._browse_gemini_outfile).grid(row=2, column=2, **pad)
            ttk.Button(self.gemini_panel, text="Run Gemini", command=self._run_gemini_clicked).grid(row=2, column=3, padx=8)
    
            row += 1
            self._update_ann_source_ui()
    
            # Font controls
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
    
        def _update_ann_source_ui(self):
            mode = self.ann_source_var.get()
            try:
                if mode == "json":
                    self.json_panel.grid()  # show
                    self.gemini_panel.grid_remove()
                else:
                    self.gemini_panel.grid()  # show
                    self.json_panel.grid_remove()
            except Exception:
                pass
    
        def _browse_font(self):
            p = filedialog.askopenfilename(title="Choose TTF/OTF font file", filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")])
            if p:
                self.fontfile_var.set(p)
    
        # --- Gemini helpers ---
        def _browse_gemini_outfile(self):
            p = filedialog.asksaveasfilename(title="Save annotations JSON as...", defaultextension=".json", filetypes=[("JSON files", "*.json")])
            if p:
                self.g_outfile_var.set(p)
    
        def _extract_pdf_text_to_temp(self) -> Optional[str]:
            pdf_path = self.ocr_pdf or self.src_pdf
            if not pdf_path:
                messagebox.showwarning("No PDF", "Choose or generate a PDF in Step 1.")
                return None
            try:
                doc = self.fitz.open(pdf_path)
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
            except Exception as e:
                messagebox.showerror("Extract failed", f"{type(e).__name__}: {e}")
                return None
    
        def _run_gemini_clicked(self):
            if not _GEMINI_AVAILABLE:
                msg = "Gemini annotator not available. Install google-genai and set GOOGLE_API_KEY (or GEMINI_API_KEY)."
                if _GEMINI_IMPORT_ERR:
                    msg += f"\nImport error: {_GEMINI_IMPORT_ERR}"
                messagebox.showerror("Gemini unavailable", msg)
                return
            # Ensure we have text extracted from the current PDF (no manual TXT selection)
            txt_path = (self.g_txt_var.get() or "").strip()
            objective = (self.g_objective_var.get() or "").strip()
            model = (self.g_model_var.get() or "gemini-2.5-flash").strip()
            max_items = int(self.g_max_items_var.get() or 12)
            if not txt_path or not Path(txt_path).exists():
                tmp_txt = self._extract_pdf_text_to_temp()
                if not tmp_txt:
                    return
                txt_path = tmp_txt
                self.g_txt_var.set(txt_path)
            if not objective:
                messagebox.showwarning("Missing objective", "Please enter an annotation objective.")
                return
            outfile = (self.g_outfile_var.get() or "").strip()
            if not outfile:
                # Default next to the current PDF with a clear suffix
                pdf_path = self.ocr_pdf or self.src_pdf
                if pdf_path:
                    outfile = str(Path(pdf_path).with_suffix("")) + "__annotations.json"
                else:
                    outfile = str(Path(txt_path).with_suffix("")) + "__annotations.json"
                self.g_outfile_var.set(outfile)
            try:
                # Run Gemini and write JSON
                gemini_annotate(
                    txt_path=txt_path,
                    objective=objective,
                    outfile=outfile,
                    model=model,
                    max_items_hint=max_items,
                )
            except Exception as e:
                messagebox.showerror("Gemini failed", f"{type(e).__name__}: {e}")
                return
            # Point the UI to the produced JSON file
            self.json_var.set(outfile)
            self.ann_json = outfile
            try:
                self.color_map = build_color_map(self.ann_json, fallback="#ff9800")
            except Exception:
                pass
            messagebox.showinfo("Done", f"Generated annotations JSON:\n{outfile}")
    
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
                note_fontname=DEFAULTS.get("note_fontname", "AnnotateNote"),
                note_fontfile=self.fontfile_var.get().strip() or None,
            )
    
        def _compute_preview_clicked(self):
            if not (self.ocr_pdf or self.src_pdf):
                messagebox.showwarning("No PDF", "Choose or generate a PDF in Step 1.")
                return
            # Ensure annotations input available based on selected source
            if self.ann_source_var.get() == "gemini" and not self.json_var.get().strip():
                # Auto-run Gemini to generate annotations from current PDF
                self._run_gemini_clicked()
            if self.ann_source_var.get() == "json" and not self.json_var.get().strip():
                messagebox.showwarning("No JSON", "Choose annotations JSON.")
                return
            if not self.json_var.get().strip():
                # Gemini run may have failed or been canceled
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
    
