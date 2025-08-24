# preview_tk.py
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
SHOW_HIGHLIGHTS = True      # draw colored highlight previews on the page image
HIGHLIGHT_STIPPLE = "gray25"  # simulates transparency; set to None to disable fill

def _tk_color(c: Optional[str], default: str = "#ff9800") -> str:
    """
    Accepts hex ('#RRGGBB') or common names ('yellow', 'red'...).
    Returns a Tk-compatible color string.
    """
    if not c:
        return default
    s = c.strip()
    if s.startswith("#") and (len(s) == 7):
        return s
    # allow simple names; Tk understands basic ones
    return s

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

def _fitz_flags(fitz):
    # mirror your highlighter flags for better search match
    ci = getattr(fitz, "TEXT_IGNORECASE", None) or getattr(fitz, "TEXT_IGNORE_CASE", 0)
    dehy = getattr(fitz, "TEXT_DEHYPHENATE", 0)
    flags = 0
    if ci: flags |= ci
    if dehy: flags |= dehy
    return flags

class PDFPreviewApp:
    def __init__(self, master, pdf_path: str, annotations_json: str):
        self.master = master
        self.master.title("PDF Notes Preview (drag boxes, then Export PDF)")
        self.pdf_path = pdf_path
        self.annotations_json = annotations_json

        # colors per quote (same logic as your annotator)
        self.color_map = _build_color_map(self.annotations_json, fallback="#ff9800")

        # Run plan-only to collect placements (UIDs, rects, etc.)
        (out, hits, notes, skipped, placements) = highlights.highlight_and_margin_comment_pdf(
            pdf_path=self.pdf_path,
            queries=[], comments={},
            annotations_json=self.annotations_json,
            plan_only=True,                 # compute only, don't draw/save
            # keep the same layout knobs you’ll use for final rendering
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

        # organize placements by page
        self.placements_by_page: Dict[int, List] = {}
        for p in placements:
            self.placements_by_page.setdefault(p.page_index, []).append(p)

        # keep the PDF open for search/highlight previews and raster
        fitz = highlights._import_fitz()
        self.fitz = fitz
        self.flags = _fitz_flags(fitz)
        self.doc = fitz.open(self.pdf_path)

        # pre-render page images
        self.page_imgs_ppm: Dict[int, bytes] = {}
        self.page_sizes: Dict[int, Tuple[int, int]] = {}
        self._rasterize_pages()

        # --- layout: top toolbar + scrollable canvas area ---
        self._build_ui()

        # state
        self.page_count = len(self.page_imgs_ppm)
        self.cur_page = 0
        self.overrides: Dict[str, Tuple[float, float, float, float]] = {}  # uid -> rect in PDF units

        # input bindings
        self.canvas.bind("<Button-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)

        # scrolling (Windows/macOS)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # scrolling (Linux)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll( 2, "units"))

        self.drag_uid = None
        self.drag_dx = 0
        self.drag_dy = 0

        self.draw_page()

    def _build_ui(self):
        # Toolbar at the TOP so it's always visible
        toolbar = ttk.Frame(self.master)
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="◀ Prev", command=self.prev_page).pack(side="left", padx=4, pady=4)
        ttk.Button(toolbar, text="Next ▶", command=self.next_page).pack(side="left", padx=4, pady=4)
        ttk.Button(toolbar, text="Export PDF", command=self.export_pdf).pack(side="right", padx=4, pady=4)

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

    def _on_mousewheel(self, event):
        # Windows/mac delta is usually +/-120 per tick
        delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")

    def _rasterize_pages(self):
        mat = self.fitz.Matrix(SCALE, SCALE)
        for i, page in enumerate(self.doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            ppm = pix.tobytes("ppm")
            self.page_imgs_ppm[i] = ppm
            self.page_sizes[i] = (pix.width, pix.height)

    def draw_page(self):
        self.canvas.delete("all")
        w, h = self.page_sizes[self.cur_page]
        # page image
        self._photo = tk.PhotoImage(data=self.page_imgs_ppm[self.cur_page])
        bg = self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags=("pageimg",))
        self.canvas.config(scrollregion=(0, 0, w, h), width=min(w, 1200), height=min(h, 900))

        # optional: draw preview highlights in correct colors
        if SHOW_HIGHLIGHTS:
            page = self.doc[self.cur_page]
            for quote, col in self.color_map.items():
                # search using same-ish flags as the main algorithm
                try:
                    hits = page.search_for(quote, flags=self.flags)
                except TypeError:
                    hits = page.search_for(quote)
                for r in hits or []:
                    cx0, cy0, cx1, cy1 = (r.x0*SCALE, r.y0*SCALE, r.x1*SCALE, r.y1*SCALE)
                    # outline + (optional) stippled fill to mimic transparency
                    kwargs = {"outline": col, "width": 2}
                    if HIGHLIGHT_STIPPLE:
                        kwargs.update({"fill": col, "stipple": HIGHLIGHT_STIPPLE})
                    self.canvas.create_rectangle(cx0, cy0, cx1, cy1, **kwargs, tags=("hit",))

        # note rectangles (draggable), using each note's color
        for pl in self.placements_by_page.get(self.cur_page, []):
            x0, y0, x1, y1 = self.overrides.get(pl.uid, pl.note_rect)
            col = self.color_map.get(pl.query, "#ff9800")
            # scale to canvas
            cx0, cy0, cx1, cy1 = (x0*SCALE, y0*SCALE, x1*SCALE, y1*SCALE)
            self.canvas.create_rectangle(cx0, cy0, cx1, cy1,
                                         outline=col, width=2, fill="",
                                         tags=("note", pl.uid))
            preview = pl.explanation.splitlines()[0][:60]
            self.canvas.create_text(cx0+6, cy0+10, anchor="nw",
                                    text=preview, fill=col,
                                    font=("Segoe UI", 10),
                                    tags=("note_text", pl.uid))

    # ---- dragging logic ----
    def _find_uid_at(self, x, y) -> Optional[str]:
        hits = self.canvas.find_overlapping(x, y, x, y)
        for obj in hits:
            tags = self.canvas.gettags(obj)
            for t in tags:
                if len(t) == 12 and all(c in "0123456789abcdef" for c in t):
                    return t
        return None

    def on_down(self, e):
        uid = self._find_uid_at(e.x, e.y)
        if not uid:
            return
        self.drag_uid = uid
        rect = self._rect_for_uid(uid)
        if rect:
            x0, y0, x1, y1 = rect
            self.drag_dx = e.x - x0
            self.drag_dy = e.y - y0

    def on_drag(self, e):
        if not self.drag_uid:
            return
        x0 = e.x - self.drag_dx
        y0 = e.y - self.drag_dy
        rect = self._rect_for_uid(self.drag_uid)
        if not rect:
            return
        _, _, w, h = self._xywh(rect)
        self._move_uid(self.drag_uid, x0, y0, x0 + w, y0 + h)

    def on_up(self, e):
        if not self.drag_uid:
            return
        rect = self._rect_for_uid(self.drag_uid)
        if rect:
            x0, y0, x1, y1 = rect
            # store back in PDF units
            self.overrides[self.drag_uid] = (x0/SCALE, y0/SCALE, x1/SCALE, y1/SCALE)
        self.drag_uid = None

    def _rect_for_uid(self, uid):
        for obj in self.canvas.find_withtag(uid):
            if "note" in self.canvas.gettags(obj):
                return self.canvas.coords(obj)
        return None

    def _xywh(self, rect_coords):
        x0, y0, x1, y1 = rect_coords
        return x0, y0, x1 - x0, y1 - y0

    def _move_uid(self, uid, x0, y0, x1, y1):
        for obj in self.canvas.find_withtag(uid):
            tags = self.canvas.gettags(obj)
            if "note" in tags:
                self.canvas.coords(obj, x0, y0, x1, y1)
            elif "note_text" in tags:
                self.canvas.coords(obj, x0 + 6, y0 + 10)

    # ---- paging & export ----
    def prev_page(self):
        self.cur_page = (self.cur_page - 1) % self.page_count
        self.draw_page()

    def next_page(self):
        self.cur_page = (self.cur_page + 1) % self.page_count
        self.draw_page()

    def export_pdf(self):
        out, hi, no, sk = highlights.highlight_and_margin_comment_pdf(
            pdf_path=self.pdf_path,
            queries=[], comments={},
            annotations_json=self.annotations_json,
            out_path=OUT_PDF,
            fixed_note_rects=self.overrides,   # <— force dragged positions
            # must match the knobs used in plan-only pass
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
        messagebox.showinfo("Export complete",
                            f"Saved: {OUT_PDF}\nHighlights={hi}  Notes={no}  Skipped={sk}")

def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: python preview_tk.py <pdf_path> <annotations_json>")
        raise SystemExit(2)
    root = tk.Tk()
    # a sensible initial window size; you can resize freely
    root.geometry("1200x900")
    PDFPreviewApp(root, sys.argv[1], sys.argv[2])
    root.mainloop()

if __name__ == "__main__":
    main()
