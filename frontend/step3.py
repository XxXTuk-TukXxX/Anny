import math
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from highlights import highlight_and_margin_comment_pdf
from .colors import build_color_map
from .defaults import DEFAULTS, SCALE, AUTO_REFRESH_AFTER_DRAG


class Step3Mixin:
        # ---------- STEP 3: Preview/Export ----------
        def _build_step3(self):
            # Toolbar
            tb = ttk.Frame(self.step3)
            tb.pack(side="top", fill="x")
            ttk.Button(tb, text="◀ Prev page", command=self._prev_page).pack(side="left", padx=4, pady=6)
            ttk.Button(tb, text="Next page ▶", command=self._next_page).pack(side="left", padx=4, pady=6)
    
            ttk.Button(tb, text="Refresh preview", command=self._refresh_preview).pack(side="left", padx=12)
            # Preview behavior toggles
            # Start with dragging enabled by default
            self.freeze_all_var = tk.BooleanVar(value=False)
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
            # Editing: double-click inside a box to edit its text
            self.canvas.bind("<Double-Button-1>", self._on_double_click)
            self.canvas.bind("<Double-1>", self._on_double_click)
            # Also bind directly to our overlay tags to ensure reliability
            self.canvas.tag_bind("note", "<Double-Button-1>", self._on_double_click)
            self.canvas.tag_bind("note_rotated", "<Double-Button-1>", self._on_double_click)
            self.canvas.tag_bind("note", "<Double-1>", self._on_double_click)
            self.canvas.tag_bind("note_rotated", "<Double-1>", self._on_double_click)
            # If the click hits the page image, capture it too and map to canvas coords
            self.canvas.tag_bind("pageimg", "<Double-Button-1>", self._on_double_click)
            self.canvas.tag_bind("pageimg", "<Double-1>", self._on_double_click)
    
            # Context menu: right-click to edit text (and future actions)
            self.canvas.bind("<Button-3>", self._on_right_click)
            self.canvas.tag_bind("note", "<Button-3>", self._on_right_click)
            self.canvas.tag_bind("note_rotated", "<Button-3>", self._on_right_click)
            self.canvas.tag_bind("pageimg", "<Button-3>", self._on_right_click)
            # macOS Ctrl-click fallback
            self.canvas.bind("<Control-Button-1>", self._on_right_click)
            self.canvas.tag_bind("note", "<Control-Button-1>", self._on_right_click)
            self.canvas.tag_bind("note_rotated", "<Control-Button-1>", self._on_right_click)
            self.canvas.tag_bind("pageimg", "<Control-Button-1>", self._on_right_click)
            # Scroll wheel
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
    
            self._drag_uid = None
            self._drag_dx = 0
            self._drag_dy = 0
            # Selection / resize state
            self._selected_uid = None
            self._handle_id = None
            self._rotate_handle_id = None
            self._resizing_uid = None
            self._resize_start_rect = None  # canvas coords [x0,y0,x1,y1]
            self._rotating_uid = None
            self._rotate_preview_id = None
            self._rotate_refresh_job = None
    
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
            # Always freeze current placements for preview so edits (text/rotation/position)
            # are accurately reflected without being reflowed by the auto-placer.
            highlight_and_margin_comment_pdf(
                pdf_path=pdf_path,
                queries=[],
                comments={},
                annotations_json=self.ann_json,
                out_path=tmp,
                fixed_note_rects=combined,
                freeze_placements=self.placements,
                note_rotations=self.rotation_overrides,
                rotate_text_with_box=True,
                note_text_overrides=self.note_text_overrides,
                note_fontsize_overrides=self.note_fontsize_overrides,
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
            # Any previous handle id becomes invalid after delete("all").
            self._handle_id = None
            self._rotate_handle_id = None
            self._rotate_preview_id = None
            w, h = self.page_sizes[self.cur_page]
            photo = tk.PhotoImage(data=self.page_imgs_ppm[self.cur_page])
            self._photo = photo  # keep a ref
            self.canvas.create_image(0, 0, anchor="nw", image=photo, tags=("pageimg",))
            self.canvas.config(scrollregion=(0, 0, w, h), width=min(w, 1200), height=min(h, 900))
    
            # overlay draggable boxes; draw rotated outline if this note has a rotation
            for pl in [p for p in self.placements if p.page_index == self.cur_page]:
                x0, y0, x1, y1 = self.fixed_overrides.get(pl.uid, pl.note_rect)
                col = self.color_map.get(pl.query, "#ff9800")
                cx0, cy0, cx1, cy1 = x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE
                # persistent rotated preview outline if any rotation defined
                ang = self.rotation_overrides.get(pl.uid)
                try:
                    angf = float(ang) if ang is not None else 0.0
                except Exception:
                    angf = 0.0
                is_rotated = abs((angf % 360.0)) > 0.5
    
                # interactive axis-aligned rectangle (used for selection / dragging)
                # If rotated, keep this invisible to avoid double outlines but still present for hit-testing.
                self.canvas.create_rectangle(
                    cx0, cy0, cx1, cy1,
                    outline=("" if is_rotated else col), width=(0 if is_rotated else 2), fill="",
                    tags=("note", f"uid:{pl.uid}")
                )
    
                if is_rotated:
                    cx = 0.5 * (cx0 + cx1)
                    cy = 0.5 * (cy0 + cy1)
                    pts = [(cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1)]
                    rad = (angf % 360.0) * math.pi / 180.0
                    c, s = math.cos(rad), math.sin(rad)
                    rpts = []
                    for x, y in pts:
                        dx, dy = x - cx, y - cy
                        rx = cx + c * dx - s * dy
                        ry = cy + s * dx + c * dy
                        rpts.extend([rx, ry])
                    self.canvas.create_polygon(
                        *rpts,
                        fill="",
                        outline=col,
                        width=2,
                        tags=("note_rotated", f"uid:{pl.uid}")
                    )
            # if a selection exists on this page, show its resize handle
            if self._selected_uid and self._rect_for_uid_canvas(self._selected_uid):
                self._show_resize_handle(self._selected_uid)
                self._show_rotate_handle(self._selected_uid)
    
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
            # update handle if this uid is selected
            if self._selected_uid == uid:
                self._update_handle_position()
                self._update_rotate_handle_position()
    
        # ---------- selection / resize handle ----------
        def _clear_selection(self):
            self._selected_uid = None
            if self._handle_id is not None:
                try:
                    self.canvas.delete(self._handle_id)
                except Exception:
                    pass
            self._handle_id = None
            if self._rotate_handle_id is not None:
                try:
                    self.canvas.delete(self._rotate_handle_id)
                except Exception:
                    pass
            self._rotate_handle_id = None
    
        def _show_resize_handle(self, uid):
            rect = self._rect_for_uid_canvas(uid)
            if not rect:
                self._clear_selection()
                return
            x0, y0, x1, y1 = rect
            r = 6  # radius in px
            hx0, hy0, hx1, hy1 = x1 - r, y0 - r, x1 + r, y0 + r
            if self._handle_id is None:
                self._handle_id = self.canvas.create_oval(
                    hx0, hy0, hx1, hy1,
                    fill="#ffffff", outline="#333333", width=1.0,
                    tags=("handle", f"uid:{uid}")
                )
            else:
                # The stored id may be invalid if canvas was cleared; recreate on failure.
                try:
                    self.canvas.coords(self._handle_id, hx0, hy0, hx1, hy1)
                    # retag to current uid
                    self.canvas.itemconfig(self._handle_id, tags=("handle", f"uid:{uid}"))
                except Exception:
                    self._handle_id = self.canvas.create_oval(
                        hx0, hy0, hx1, hy1,
                        fill="#ffffff", outline="#333333", width=1.0,
                        tags=("handle", f"uid:{uid}")
                    )
            # make sure handle is on top
            try:
                self.canvas.tag_raise(self._handle_id)
            except Exception:
                pass
    
        def _update_handle_position(self):
            if self._selected_uid and self._handle_id is not None:
                self._show_resize_handle(self._selected_uid)
    
        def _hit_handle(self, x, y) -> Optional[str]:
            tol = 6
            for obj in self.canvas.find_overlapping(x - tol, y - tol, x + tol, y + tol):
                tags = self.canvas.gettags(obj)
                if tags and "handle" in tags:
                    for t in tags:
                        if t.startswith("uid:"):
                            return t[4:]
            return None
    
        # ---------- rotate handle ----------
        def _show_rotate_handle(self, uid):
            rect = self._rect_for_uid_canvas(uid)
            if not rect:
                return
            x0, y0, x1, y1 = rect
            cx = 0.5 * (x0 + x1)
            offset = 14  # pixels above top edge
            r = 5
            hx0, hy0, hx1, hy1 = cx - r, y0 - offset - r, cx + r, y0 - offset + r
            if self._rotate_handle_id is None:
                self._rotate_handle_id = self.canvas.create_oval(
                    hx0, hy0, hx1, hy1,
                    fill="#ffffff", outline="#333333", width=1.0,
                    tags=("rotate_handle", f"uid:{uid}")
                )
            else:
                try:
                    self.canvas.coords(self._rotate_handle_id, hx0, hy0, hx1, hy1)
                    self.canvas.itemconfig(self._rotate_handle_id, tags=("rotate_handle", f"uid:{uid}"))
                except Exception:
                    self._rotate_handle_id = self.canvas.create_oval(
                        hx0, hy0, hx1, hy1,
                        fill="#ffffff", outline="#333333", width=1.0,
                        tags=("rotate_handle", f"uid:{uid}")
                    )
            try:
                self.canvas.tag_raise(self._rotate_handle_id)
            except Exception:
                pass
    
        def _update_rotate_handle_position(self):
            if self._selected_uid and self._rotate_handle_id is not None:
                self._show_rotate_handle(self._selected_uid)
    
        def _hit_rotate_handle(self, x, y) -> Optional[str]:
            tol = 6
            for obj in self.canvas.find_overlapping(x - tol, y - tol, x + tol, y + tol):
                tags = self.canvas.gettags(obj)
                if tags and "rotate_handle" in tags:
                    for t in tags:
                        if t.startswith("uid:"):
                            return t[4:]
            return None
    
        def _on_down(self, e):
            # Convert to canvas coordinates to respect scrolling
            cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
            # Rotation handle hit?
            r_uid = self._hit_rotate_handle(cx, cy)
            if r_uid:
                self._rotating_uid = r_uid
                self._selected_uid = r_uid
                self._show_resize_handle(r_uid)
                self._show_rotate_handle(r_uid)
                # Hide the axis-aligned rectangle while rotating to avoid duplicate visuals
                try:
                    for obj in self.canvas.find_withtag(f"uid:{r_uid}"):
                        if "note" in self.canvas.gettags(obj):
                            self.canvas.itemconfigure(obj, state='hidden')
                except Exception:
                    pass
                return
            # Prioritize resize handle hit
            h_uid = self._hit_handle(cx, cy)
            if h_uid:
                self._resizing_uid = h_uid
                self._resize_start_rect = self._rect_for_uid_canvas(h_uid)
                self._selected_uid = h_uid
                return
            uid = self._find_uid_at(cx, cy)
            if not uid:
                self._clear_selection()
                return
            self._selected_uid = uid
            self._show_resize_handle(uid)
            # start dragging move
            self._drag_uid = uid
            rect = self._rect_for_uid_canvas(uid)
            if rect:
                x0, y0, x1, y1 = rect
                self._drag_dx = cx - x0
                self._drag_dy = cy - y0
    
        def _on_drag(self, e):
            cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
            # Rotating?
            if self._rotating_uid:
                rect = self._rect_for_uid_canvas(self._rotating_uid)
                if rect:
                    x0, y0, x1, y1 = rect
                    cx0 = 0.5 * (x0 + x1)
                    cy0 = 0.5 * (y0 + y1)
                    ang = math.degrees(math.atan2(cy - cy0, cx - cx0))
                    # Normalize angle to [0,360)
                    ang = (ang + 360.0) % 360.0
                    self.rotation_overrides[self._rotating_uid] = ang
                    # Update rotate handle and show a live rotated polygon preview
                    self._update_rotate_handle_position()
                    self._update_rotate_preview_polygon(self._rotating_uid, rect, ang)
    
                    # If auto-refresh is enabled, throttle preview rebuilds during drag
                    try:
                        do_auto = bool(self.auto_refresh_var.get())
                    except Exception:
                        do_auto = bool(AUTO_REFRESH_AFTER_DRAG)
                    if do_auto:
                        self._schedule_rotate_preview_refresh()
                return
            # Resizing has priority
            if self._resizing_uid and self._resize_start_rect:
                x0, y0, x1, y1 = self._resize_start_rect
                # Anchor bottom-left (x0,y1); move top-right to cursor
                # Enforce minimum width/height
                try:
                    min_w = float(self.min_width_var.get()) * SCALE
                except Exception:
                    min_w = float(DEFAULTS.get("min_note_width", 48)) * SCALE
                try:
                    fs = float(self.fontsize_var.get())
                except Exception:
                    fs = float(DEFAULTS.get("note_fontsize", 9.0))
                min_h = max(18.0, (2 * fs + 8.0)) * SCALE
    
                new_x1 = max(cx, x0 + min_w)
                new_y0 = min(cy, y1 - min_h)
    
                # Clamp within page
                W, H = self.page_sizes[self.cur_page]
                new_x1 = min(new_x1, W)
                new_y0 = max(new_y0, 0)
    
                self._move_uid(self._resizing_uid, x0, new_y0, new_x1, y1)
                return
    
            if not self._drag_uid:
                return
            x0 = cx - self._drag_dx
            y0 = cy - self._drag_dy
            rect = self._rect_for_uid_canvas(self._drag_uid)
            if not rect:
                return
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            self._move_uid(self._drag_uid, x0, y0, x0 + w, y0 + h)
    
        def _on_up(self, e):
            # Finish rotation
            if self._rotating_uid:
                uid = self._rotating_uid
                self._rotating_uid = None
                # Clear any live rotated preview polygon
                if self._rotate_preview_id is not None:
                    try:
                        self.canvas.delete(self._rotate_preview_id)
                    except Exception:
                        pass
                    self._rotate_preview_id = None
                # Unhide the axis-aligned rectangle for the selected uid
                try:
                    for obj in self.canvas.find_withtag(f"uid:{uid}"):
                        if "note" in self.canvas.gettags(obj):
                            self.canvas.itemconfigure(obj, state='normal')
                except Exception:
                    pass
                try:
                    do_auto = bool(self.auto_refresh_var.get())
                except Exception:
                    do_auto = bool(AUTO_REFRESH_AFTER_DRAG)
                if do_auto:
                    self._refresh_preview()
                return
            # If resizing, finalize
            if self._resizing_uid:
                rect = self._rect_for_uid_canvas(self._resizing_uid)
                if rect:
                    x0, y0, x1, y1 = rect
                    self.fixed_overrides[self._resizing_uid] = (x0 / SCALE, y0 / SCALE, x1 / SCALE, y1 / SCALE)
                self._resizing_uid = None
                self._resize_start_rect = None
                try:
                    do_auto = bool(self.auto_refresh_var.get())
                except Exception:
                    do_auto = bool(AUTO_REFRESH_AFTER_DRAG)
                if do_auto:
                    self._refresh_preview()
                return
    
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
    
        # ---------- rotation preview helpers ----------
        def _update_rotate_preview_polygon(self, uid: str, rect: List[float], ang_deg: float):
            """Draw or update a rotated polygon preview for the given rect at angle.
            rect is canvas coords [x0,y0,x1,y1].
            """
            if not rect or len(rect) < 4:
                return
            x0, y0, x1, y1 = rect
            cx = 0.5 * (x0 + x1)
            cy = 0.5 * (y0 + y1)
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            rad = (ang_deg % 360.0) * math.pi / 180.0
            c, s = math.cos(rad), math.sin(rad)
            rpts = []
            for x, y in pts:
                dx, dy = x - cx, y - cy
                rx = cx + c * dx - s * dy
                ry = cy + s * dx + c * dy
                rpts.extend([rx, ry])
    
            # Determine outline color from the note rectangle item (if available)
            outline = "#ff9800"
            try:
                for obj in self.canvas.find_withtag(f"uid:{uid}"):
                    if "note" in self.canvas.gettags(obj):
                        outline = self.canvas.itemcget(obj, "outline") or outline
                        break
            except Exception:
                pass
    
            if self._rotate_preview_id is None:
                # Transparent fill, just an outline
                self._rotate_preview_id = self.canvas.create_polygon(
                    *rpts,
                    fill="",
                    outline=outline,
                    width=2,
                    tags=("rotate_preview", f"uid:{uid}")
                )
            else:
                try:
                    self.canvas.coords(self._rotate_preview_id, *rpts)
                    self.canvas.itemconfig(self._rotate_preview_id, outline=outline, tags=("rotate_preview", f"uid:{uid}"))
                except Exception:
                    self._rotate_preview_id = self.canvas.create_polygon(
                        *rpts,
                        fill="",
                        outline=outline,
                        width=2,
                        tags=("rotate_preview", f"uid:{uid}")
                    )
            try:
                self.canvas.tag_raise(self._rotate_preview_id)
            except Exception:
                pass
    
        def _schedule_rotate_preview_refresh(self, delay_ms: int = 220):
            """Throttle heavy preview rebuilds during rotation by debouncing.
            Always cancel any pending job and schedule one trailing update.
            """
            # Cancel any pending refresh to achieve trailing-edge debounce
            if self._rotate_refresh_job is not None:
                try:
                    self.after_cancel(self._rotate_refresh_job)
                except Exception:
                    pass
                self._rotate_refresh_job = None
    
            def _do():
                self._rotate_refresh_job = None
                self._refresh_preview()
            try:
                self._rotate_refresh_job = self.after(delay_ms, _do)
            except Exception:
                # If scheduling fails, do an immediate refresh as fallback
                self._refresh_preview()
    
        def _on_mousewheel(self, event):
            delta = int(-1 * (event.delta / 120))
            self.canvas.yview_scroll(delta, "units")
    
        def _refresh_preview(self):
            self._build_exact_preview_pdf()
            self._draw_page()
    
        # ---------- text editing ----------
        def _uid_from_point(self, cx: float, cy: float) -> Optional[str]:
            """Robustly resolve a note uid from a canvas point.
            Strategy:
              1) Try item under cursor ('current').
              2) Geometric test: check if point lies inside any (possibly rotated)
                 note rectangle on the current page.
              3) Expand overlap search radius and pick topmost hit.
              4) Fallback to axis-aligned hit test.
            """
            # 1) Item under cursor if any
            try:
                cur = self.canvas.find_withtag("current")
                if cur:
                    tags = self.canvas.gettags(cur[0])
                    for t in tags:
                        if t.startswith("uid:"):
                            return t[4:]
            except Exception:
                pass
    
            # 2) Geometric test against our placements (handles interior clicks)
            cand = None
            best_area = None
            for pl in [p for p in self.placements if p.page_index == self.cur_page]:
                try:
                    x0, y0, x1, y1 = self.fixed_overrides.get(pl.uid, pl.note_rect)
                except Exception:
                    continue
                cx0, cy0, cx1, cy1 = x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE
                # center
                mx = 0.5 * (cx0 + cx1)
                my = 0.5 * (cy0 + cy1)
                # inverse-rotate the click point by note rotation
                ang = 0.0
                try:
                    ra = self.rotation_overrides.get(pl.uid)
                    if ra is not None:
                        ang = float(ra)
                except Exception:
                    ang = 0.0
                if abs((ang % 360.0)) > 0.5:
                    rad = - (ang % 360.0) * math.pi / 180.0  # inverse
                    c, s = math.cos(rad), math.sin(rad)
                    dx, dy = cx - mx, cy - my
                    rx = mx + c * dx - s * dy
                    ry = my + s * dx + c * dy
                else:
                    rx, ry = cx, cy
                if (cx0 <= rx <= cx1) and (cy0 <= ry <= cy1):
                    area = (cx1 - cx0) * (cy1 - cy0)
                    if best_area is None or area < best_area:
                        cand = pl.uid
                        best_area = area
            if cand:
                return cand
    
            # 3) Expand search radius around the click and pick topmost hit
            for tol in (1, 3, 6, 10):
                try:
                    hits = self.canvas.find_overlapping(cx - tol, cy - tol, cx + tol, cy + tol)
                    for obj in reversed(hits):
                        tags = self.canvas.gettags(obj)
                        if not tags:
                            continue
                        for t in tags:
                            if t.startswith("uid:"):
                                return t[4:]
                except Exception:
                    pass
    
            # 4) Fallback to axis-aligned rectangle hit-test
            return self._find_uid_at(cx, cy)
    
        def _canvas_point_from_event(self, e):
            """Return canvas coordinates (cx, cy) for a mouse event regardless of widget."""
            try:
                if e.widget is self.canvas:
                    return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
                # Map global pointer position to canvas coordinates
                x = self.winfo_pointerx() - self.canvas.winfo_rootx()
                y = self.winfo_pointery() - self.canvas.winfo_rooty()
                return self.canvas.canvasx(x), self.canvas.canvasy(y)
            except Exception:
                return 0.0, 0.0
    
        def _on_double_click(self, e):
            cx, cy = self._canvas_point_from_event(e)
            uid = self._uid_from_point(cx, cy)
            # Fallback: if click is inside currently selected rect, use it
            if not uid and self._selected_uid:
                rect = self._rect_for_uid_canvas(self._selected_uid)
                if rect and len(rect) >= 4:
                    x0, y0, x1, y1 = rect[:4]
                    if x0 <= cx <= x1 and y0 <= cy <= y1:
                        uid = self._selected_uid
            # Fallback 2: choose nearest note on this page by center distance
            if not uid:
                best_uid = None
                best_d2 = None
                for pl in [p for p in self.placements if p.page_index == self.cur_page]:
                    try:
                        x0, y0, x1, y1 = self.fixed_overrides.get(pl.uid, pl.note_rect)
                    except Exception:
                        continue
                    mx = 0.5 * (x0 + x1) * SCALE
                    my = 0.5 * (y0 + y1) * SCALE
                    dx = mx - cx; dy = my - cy
                    d2 = dx*dx + dy*dy
                    if (best_d2 is None) or (d2 < best_d2):
                        best_d2 = d2; best_uid = pl.uid
                # use if reasonably close (within ~64 px)
                if best_uid is not None and (best_d2 is None or best_d2 <= (64*64)):
                    uid = best_uid
            if not uid:
                return
            self._selected_uid = uid
            self._show_resize_handle(uid)
            self._open_text_editor(uid)
    
        # ---------- context menu (right-click) ----------
        def _on_right_click(self, e):
            cx, cy = self._canvas_point_from_event(e)
            uid = self._uid_from_point(cx, cy)
            if not uid:
                return
            self._selected_uid = uid
            self._show_resize_handle(uid)
            # Build and show a simple context menu
            try:
                if hasattr(self, "_ctx_menu") and self._ctx_menu is not None:
                    try:
                        self._ctx_menu.destroy()
                    except Exception:
                        pass
                self._ctx_menu = tk.Menu(self, tearoff=0)
                self._ctx_menu.add_command(
                    label="Edit text…",
                    command=lambda u=uid: self._open_text_editor(u)
                )
                # Future: add rotate/reset or delete here
                x_root = self.winfo_pointerx()
                y_root = self.winfo_pointery()
                try:
                    self._ctx_menu.tk_popup(x_root, y_root)
                finally:
                    self._ctx_menu.grab_release()
            except Exception:
                # Fallback: open editor directly
                self._open_text_editor(uid)
    
        def _open_text_editor(self, uid: str):
            # find placement
            pl = None
            for p in self.placements:
                if getattr(p, 'uid', None) == uid:
                    pl = p
                    break
            if pl is None:
                return
    
            top = tk.Toplevel(self)
            top.title("Edit note text")
            top.transient(self)
            top.grab_set()
            try:
                top.lift()
                top.focus_force()
            except Exception:
                pass
    
            # Top toolbar for text style
            toolbar = ttk.Frame(top)
            toolbar.pack(fill="x", padx=8, pady=(8, 4))
    
            # Resolve current defaults for this note
            try:
                base_color = self.note_text_overrides.get(uid)
                if not base_color:
                    # Prefer per-query color map if available, else global text color
                    base_color = self.color_map.get(getattr(pl, 'query', ''), self.note_text_var.get() or 'black')
            except Exception:
                base_color = self.note_text_var.get() or 'black'
            try:
                base_size = float(self.note_fontsize_overrides.get(uid)) if uid in self.note_fontsize_overrides else float(self.fontsize_var.get())
            except Exception:
                base_size = float(DEFAULTS.get('note_fontsize', 9.0))
    
            color_var = tk.StringVar(value=base_color)
            size_var = tk.DoubleVar(value=base_size)
    
            def pick_color():
                try:
                    _, hx = colorchooser.askcolor(color=color_var.get() or '#000000', title='Pick text color')
                    if hx:
                        color_var.set(hx)
                        try:
                            swatch.configure(bg=hx)
                        except Exception:
                            pass
                except Exception:
                    pass
    
            ttk.Label(toolbar, text="Text color:").pack(side="left")
            ttk.Button(toolbar, text="Pick...", command=pick_color).pack(side="left", padx=(4, 6))
            # Small swatch to preview color
            swatch = tk.Label(toolbar, text="  ", bg=base_color if base_color else '#000000', relief='solid', width=2)
            swatch.pack(side="left", padx=(0, 12))
    
            ttk.Label(toolbar, text="Font size:").pack(side="left")
            sz = tk.Spinbox(toolbar, from_=6, to=72, increment=1, textvariable=size_var, width=5)
            sz.pack(side="left", padx=(4, 0))
    
            txt = tk.Text(top, wrap="word", width=64, height=12)
            txt.insert("1.0", getattr(pl, 'explanation', ""))
            txt.pack(fill="both", expand=True, padx=8, pady=(4, 4))
    
            btns = ttk.Frame(top)
            btns.pack(fill="x", padx=8, pady=(0, 8))
    
            def do_save(event=None):
                new_text = txt.get("1.0", "end-1c")
                try:
                    pl.explanation = new_text
                except Exception:
                    # if placements are non-dataclass objects
                    try:
                        setattr(pl, 'explanation', new_text)
                    except Exception:
                        pass
                # Persist per-note style overrides
                try:
                    col = (color_var.get() or '').strip()
                    if col:
                        self.note_text_overrides[uid] = col
                except Exception:
                    pass
                try:
                    fs = float(size_var.get())
                    if fs > 0:
                        self.note_fontsize_overrides[uid] = fs
                except Exception:
                    pass
                top.destroy()
                # Rebuild preview to reflect text change when frozen
                self._refresh_preview()
    
            def do_cancel(event=None):
                top.destroy()
    
            ttk.Button(btns, text="Save", command=do_save).pack(side="right", padx=4)
            ttk.Button(btns, text="Cancel", command=do_cancel).pack(side="right", padx=4)
            txt.focus_set()
            txt.bind("<Control-Return>", do_save)
            txt.bind("<Escape>", do_cancel)
    
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
                # Always freeze current placements and rotations when exporting so the
                # PDF reflects the user's interactive edits precisely.
                out, hi, no, sk = highlight_and_margin_comment_pdf(
                    pdf_path=pdf_path,
                    queries=[],
                    comments={},
                    annotations_json=self.ann_json,
                    out_path=self.export_var.get().strip(),
                    fixed_note_rects=combined,
                    freeze_placements=self.placements,
                    note_rotations=self.rotation_overrides,
                    rotate_text_with_box=True,
                    note_text_overrides=self.note_text_overrides,
                    note_fontsize_overrides=self.note_fontsize_overrides,
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
    
    
