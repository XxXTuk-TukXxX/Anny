# preview_tk.py  (Option B: true-to-PDF preview)
import os
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, Tuple, List, Optional
import json

# import your module (must be in the same folder or on PYTHONPATH)
import highlights  # your highlights.py

# --- tweakables ---
SCALE = 1.5                 # raster zoom factor
OUT_PDF = "Myth_annotated_preview.pdf"
AUTO_REFRESH_AFTER_DRAG = True   # rebuild the exact preview after each drag

# Use the SAME settings for plan-only, preview render, and export:
DEFAULT_ANNOTATION_SETTINGS = dict(
    note_width=240,
    min_note_width=48,
    note_fontsize=9.0,
    note_fill=None, note_border=None, note_border_width=0,
    note_text="red", draw_leader=False, leader_color=None,
    allow_column_footer=True,
    column_footer_max_offset=250,
    max_vertical_offset=90,
    max_scan=420,
    side="outer",
    allow_center_gutter=True,
    center_gutter_tolerance=48.0,
    dedupe_scope="page",
    note_fontname="PatrickHand",
    note_fontfile=r".\fonts\PatrickHand-Regular.ttf",
)

def _tk_color(c: Optional[str], default: str = "#ff9800") -> str:
    if not c:
        return default
    s = c.strip()
    if s.startswith("#") and (len(s) == 7):
        return s
    return s  # allow Tk named colors

def _build_color_map(annotations_json: str, fallback: str = "#ff9800") -> Dict[str, str]:
    p = Path(annotations_json)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    cmap: Dict[str, str] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        q = (row.get("quote") or row.get("query") or "").strip()
        if not q:
            continue
        cmap[q] = _tk_color(row.get("color"), fallback)
    return cmap

class PDFPreviewApp:
    def __init__(self, master, pdf_path: str, annotations_json: str):
        self.master = master
        self.master.title("PDF Notes Preview (EXACT) — drag boxes, Refresh, Export")
        self.pdf_path = pdf_path
        self.annotations_json = annotations_json
        self.settings = dict(DEFAULT_ANNOTATION_SETTINGS)  # one source of truth

        # colors per quote
        self.color_map = _build_color_map(self.annotations_json, fallback="#ff9800")

        # ---- PLAN: compute placements (no drawing)
        (_, hits, notes, skipped, placements) = highlights.highlight_and_margin_comment_pdf(
            pdf_path=self.pdf_path,
            queries=[], comments={},
            annotations_json=self.annotations_json,
            plan_only=True,
            **self.settings
        )
        self.placements: List = placements
        self.page_count = None
        self.cur_page = 0
        self.overrides: Dict[str, Tuple[float, float, float, float]] = {}  # uid -> rect in PDF units
        self._preview_pdf_path: Optional[str] = None

        # PyMuPDF (from your helper)
        self.fitz = highlights._import_fitz()
        self.doc = None
        self.page_imgs_ppm: Dict[int, bytes] = {}
        self.page_sizes: Dict[int, Tuple[int, int]] = {}

        # UI
        self._build_ui()

        # Build the first exact preview from the planned rectangles
        self._build_exact_preview_pdf()
        self._draw_page()

        messagebox.showinfo("Preview ready",
                            f"Found {hits} highlights, {notes} notes (skipped {skipped}).")

    # ---------- helpers ----------
    def _planned_rect_map(self) -> Dict[str, Tuple[float,float,float,float]]:
        # uid -> planned rect from plan-only phase
        return {p.uid: p.note_rect for p in self.placements}

    def _build_exact_preview_pdf(self):
        """Render a temporary annotated PDF that exactly matches export."""
        # combine plan-only rectangles with any dragged overrides
        planned = self._planned_rect_map()
        combined = {**planned, **self.overrides}

        # make a temp file path
        fd, tmp = tempfile.mkstemp(suffix="_annot_preview.pdf")
        os.close(fd)
        self._preview_pdf_path = tmp

        # draw using the real engine (identical code path to export)
        highlights.highlight_and_margin_comment_pdf(
            pdf_path=self.pdf_path,
            queries=[], comments={},
            annotations_json=self.annotations_json,
            out_path=tmp,
            fixed_note_rects=combined,
            **self.settings
        )

        # open and rasterize
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = self.fitz.open(tmp)
        self._rasterize_pages()
        self.page_count = len(self.page_imgs_ppm)
        self.cur_page = max(0, min(self.cur_page, self.page_count - 1))

    def _rasterize_pages(self):
        self.page_imgs_ppm.clear()
        self.page_sizes.clear()
        mat = self.fitz.Matrix(SCALE, SCALE)
        for i, page in enumerate(self.doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            self.page_imgs_ppm[i] = pix.tobytes("ppm")
            self.page_sizes[i] = (pix.width, pix.height)

    # ---------- UI ----------
    def _build_ui(self):
        # Toolbar at the top
        toolbar = ttk.Frame(self.master)
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="◀ Prev", command=self.prev_page).pack(side="left", padx=4, pady=4)
        ttk.Button(toolbar, text="Next ▶", command=self.next_page).pack(side="left", padx=4, pady=4)
        ttk.Button(toolbar, text="Refresh preview", command=self._refresh_preview).pack(side="left", padx=12, pady=4)
        ttk.Button(toolbar, text="Export PDF", command=self.export_pdf).pack(side="right", padx=8, pady=4)

        # Scrollable canvas area below toolbar
        outer = ttk.Frame(self.master)
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

        # input bindings for dragging overlays
        self.canvas.bind("<Button-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        # scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll( 2, "units"))

        self.drag_uid = None
        self.drag_dx = 0
        self.drag_dy = 0

    def _refresh_preview(self):
        self._build_exact_preview_pdf()
        self._draw_page()

    # ---------- drawing & paging ----------
    def _placements_for_page(self, page_index: int) -> List:
        return [p for p in self.placements if p.page_index == page_index]

    def _rect_for_uid_pdf_units(self, uid: str, page_index: int):
        # prefer override, else planned
        if uid in self.overrides:
            return self.overrides[uid]
        for p in self._placements_for_page(page_index):
            if p.uid == uid:
                return p.note_rect
        return None

    def _draw_page(self):
        self.canvas.delete("all")
        w, h = self.page_sizes[self.cur_page]
        # show the raster of the temporary PDF (already has real notes + highlights)
        self._photo = tk.PhotoImage(data=self.page_imgs_ppm[self.cur_page])
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags=("pageimg",))
        self.canvas.config(scrollregion=(0, 0, w, h), width=min(w, 1200), height=min(h, 900))

        # overlay simple draggable rectangles (no text rendered in Tk)
        for pl in self._placements_for_page(self.cur_page):
            x0, y0, x1, y1 = self._rect_for_uid_pdf_units(pl.uid, self.cur_page)
            col = self.color_map.get(pl.query, "#ff9800")
            cx0, cy0, cx1, cy1 = (x0*SCALE, y0*SCALE, x1*SCALE, y1*SCALE)
            self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                         outline=col, width=2, fill="",
                                         tags=("note", pl.uid))

    def prev_page(self):
        if self.page_count:
            self.cur_page = (self.cur_page - 1) % self.page_count
            self._draw_page()

    def next_page(self):
        if self.page_count:
            self.cur_page = (self.cur_page + 1) % self.page_count
            self._draw_page()

    # ---------- dragging ----------
    def _find_uid_at(self, x, y) -> Optional[str]:
        hits = self.canvas.find_overlapping(x, y, x, y)
        for obj in hits:
            tags = self.canvas.gettags(obj)
            for t in tags:
                if len(t) == 12 and all(c in "0123456789abcdef" for c in t):
                    return t
        return None

    def _rect_for_uid_canvas(self, uid):
        for obj in self.canvas.find_withtag(uid):
            if "note" in self.canvas.gettags(obj):
                return self.canvas.coords(obj)
        return None

    def _move_uid(self, uid, x0, y0, x1, y1):
        for obj in self.canvas.find_withtag(uid):
            if "note" in self.canvas.gettags(obj):
                self.canvas.coords(obj, x0, y0, x1, y1)

    def on_down(self, e):
        uid = self._find_uid_at(e.x, e.y)
        if not uid:
            return
        self.drag_uid = uid
        rect = self._rect_for_uid_canvas(uid)
        if rect:
            x0, y0, x1, y1 = rect
            self.drag_dx = e.x - x0
            self.drag_dy = e.y - y0

    def on_drag(self, e):
        if not self.drag_uid:
            return
        x0 = e.x - self.drag_dx
        y0 = e.y - self.drag_dy
        rect = self._rect_for_uid_canvas(self.drag_uid)
        if not rect:
            return
        w = rect[2]-rect[0]
        h = rect[3]-rect[1]
        self._move_uid(self.drag_uid, x0, y0, x0 + w, y0 + h)

    def on_up(self, e):
        if not self.drag_uid:
            return
        rect = self._rect_for_uid_canvas(self.drag_uid)
        if rect:
            x0, y0, x1, y1 = rect
            # store back in PDF units
            self.overrides[self.drag_uid] = (x0/SCALE, y0/SCALE, x1/SCALE, y1/SCALE)
        self.drag_uid = None
        if AUTO_REFRESH_AFTER_DRAG:
            self._refresh_preview()

    def _on_mousewheel(self, event):
        delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")

    # ---------- export ----------
    def export_pdf(self):
        planned = self._planned_rect_map()
        combined = {**planned, **self.overrides}  # lock EVERY note

        out, hi, no, sk = highlights.highlight_and_margin_comment_pdf(
            pdf_path=self.pdf_path,
            queries=[], comments={},
            annotations_json=self.annotations_json,
            out_path=OUT_PDF,
            fixed_note_rects=combined,   # same rects as preview
            **self.settings
        )
        messagebox.showinfo("Export complete",
                            f"Saved: {OUT_PDF}\nHighlights={hi}  Notes={no}  Skipped={sk}")

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
        self.master.destroy()

def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: python preview_tk.py <pdf_path> <annotations_json>")
        raise SystemExit(2)
    root = tk.Tk()
    root.geometry("1200x900")
    PDFPreviewApp(root, sys.argv[1], sys.argv[2])
    root.mainloop()

if __name__ == "__main__":
    main()
