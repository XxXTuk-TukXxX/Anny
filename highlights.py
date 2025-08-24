# highlights.py
# Search + highlight + margin/gutter comments without covering text.
# Python 3.8+ | Works across multiple PyMuPDF (pymupdf) versions.

from pathlib import Path
from typing import Tuple, Union, Sequence, Optional, List, Dict, Callable
from collections import defaultdict
import textwrap
import json

from dataclasses import dataclass
import hashlib


# --- ADD: data model for one planned note ---
@dataclass
class NotePlacement:
    uid: str                     # stable id (page + text + anchor)
    page_index: int              # 0-based page
    query: str                   # matched query text
    explanation: str             # note body (already normalized)
    anchor_rect: Tuple[float, float, float, float]   # (x0,y0,x1,y1) around the hit's block
    note_rect: Tuple[float, float, float, float]     # final box to draw
    leader_from: Optional[Tuple[float, float]]       # start point (box edge midpoint) or None
    leader_to: Optional[Tuple[float, float]]         # end point (block edge midpoint) or None

def _rect_tuple(r) -> Tuple[float, float, float, float]:
    rr = getattr(r, "rect", r)
    return (float(rr.x0), float(rr.y0), float(rr.x1), float(rr.y1))

def _make_uid(page_index: int, norm_ct: str, cx: float, cy: float) -> str:
    # deterministic across runs (unlike Python's randomized hash())
    base = f"{page_index}|{norm_ct}|{round(cx,2)}|{round(cy,2)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


Color = Tuple[float, float, float]

# ---------------- version-proof import & flags ----------------
def _import_fitz():
    try:
        import pymupdf as fitz
    except Exception:
        import fitz  # legacy alias (should still be pymupdf)
    if not hasattr(fitz, "open"):
        raise RuntimeError(
            "PyMuPDF not found / wrong 'fitz'. "
            "Fix with:\n  pip uninstall -y fitz && pip install -U pymupdf"
        )
    return fitz

def _pick_flag(fitz, names: Sequence[str], default=None):
    for n in names:
        if hasattr(fitz, n):
            return getattr(fitz, n)
    return default

# ---------------- colors & drawing ----------------
_NAMED_COLORS = {
    "yellow": (1.0, 1.0, 0.0), "red": (1.0, 0.0, 0.0), "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0), "cyan": (0.0, 1.0, 1.0), "magenta": (1.0, 0.0, 1.0),
    "orange": (1.0, 0.5, 0.0), "pink": (1.0, 0.75, 0.8), "purple": (0.5, 0.0, 0.5),
    "gray": (0.5, 0.5, 0.5), "black": (0.0, 0.0, 0.0), "white": (1.0, 1.0, 1.0),
}

def _parse_color(c: Union[str, Color]) -> Color:
    if isinstance(c, (tuple, list)) and len(c) == 3:
        r, g, b = map(float, c)
        clamp = lambda x: max(0.0, min(1.0, x))
        return clamp(r), clamp(g), clamp(b)
    if isinstance(c, str):
        s = c.strip().lower()
        if s in _NAMED_COLORS:
            return _NAMED_COLORS[s]
        if s.startswith("#") and len(s) == 7:
            return tuple(int(s[i:i+2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore
    raise ValueError(f"Unrecognized color: {c!r}")

def _parse_optional_color(c):
    if c is None:
        return None
    if isinstance(c, str) and c.strip().lower() in ("none", "transparent", ""):
        return None
    return _parse_color(c)

def _draw_rect(page, rect, *, stroke: Optional[Color], fill: Optional[Color],
               width: float = 1.0, opacity: Optional[float] = None):
    try:
        return page.draw_rect(rect, color=stroke, fill=fill, width=width, opacity=opacity)
    except TypeError:
        try:
            return page.draw_rect(rect, color=stroke, fill=fill, width=width)
        except (TypeError, AttributeError):
            pass
    try:
        return page.drawRect(rect, color=stroke, fill=fill, width=width)
    except Exception:
        return None

def _draw_note_box(page, pos, *, stroke_rgb, fill_rgb, width, opacity):
    if width is None or width <= 0:
        return None
    if stroke_rgb is None and fill_rgb is None:
        return None
    return _draw_rect(page, pos, stroke=stroke_rgb, fill=fill_rgb,
                      width=width, opacity=opacity)

# ---------- text insertion (TextWriter fallback) ----------
def _sanitize_punct(s: str) -> str:
    return (s.replace("’", "'").replace("‘", "'")
             .replace("“", '"').replace("”", '"')
             .replace("—", "-").replace("–", "-"))

def _font_object(fontname: Optional[str], fontfile: Optional[str]):
    """Return a fitz.Font object if possible (prefer file), else None."""
    fitz = _import_fitz()
    try:
        if fontfile and Path(fontfile).exists():
            return fitz.Font(file=str(fontfile))
    except Exception:
        pass
    try:
        if fontname:
            return fitz.Font(fontname=fontname)
    except Exception:
        pass
    try:
        return fitz.Font(fontname="helv")
    except Exception:
        return None

def _wrap_with_font_metrics(text: str, width: float, fontsize: float,
                            font_obj, get_len_fallback, tightness=0.96,
                            line_height_factor=1.18):
    """Wrap text to 'width' using font_obj.text_length if available."""
    def wlen(s: str) -> float:
        try:
            if font_obj is not None and hasattr(font_obj, "text_length"):
                return float(font_obj.text_length(s, fontsize))
        except Exception:
            pass
        if get_len_fallback is not None:
            try:
                return float(get_len_fallback(s, fontname="helv", fontsize=fontsize))
            except Exception:
                pass
        return 0.5 * fontsize * len(s)

    max_w = max(1.0, width)
    lines = []
    for para in (text.splitlines() or [""]):
        if not para:
            lines.append("")
            continue
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if wlen(trial) * float(tightness) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)

    line_h = line_height_factor * fontsize
    height = max(2*fontsize, len(lines) * line_h)
    return lines, height

def _register_font_alias(doc, page, fontfile: Union[str, Path], alias: str = "custom_font") -> Optional[str]:
    """
    Make the TTF/OTF available under a font *name* so page.insert_text can use it.
    Tries doc.insert_font (newer), then page.insert_font (older). Returns the alias
    if registration succeeded, else None.
    """
    p = Path(fontfile)
    if not p.exists():
        return None
    fontfile = str(p.resolve())

    # Newer API
    try:
        if hasattr(doc, "insert_font"):
            doc.insert_font(fontname=alias, fontfile=fontfile)
            return alias
    except Exception:
        pass

    # Older API (some PyMuPDF builds expose it on Page)
    try:
        if hasattr(page, "insert_font"):
            page.insert_font(fontname=alias, fontfile=fontfile)
            return alias
    except Exception:
        pass

    return None


def _draw_paragraph_lines(page, rect, text: str, *,
                          fontsize: float, color: Optional[Color],
                          fontname: Optional[str], fontfile: Optional[Union[str, Path]],
                          tightness=0.96, line_height_factor=1.18,
                          debug: bool = False) -> int:
    """Wrap + draw each line with page.insert_text. If possible, first register
    the TTF with an alias and draw via fontname=<alias> (works on finicky builds)."""
    fitz = _import_fitz()
    doc = getattr(page, "parent", None)

    # Try to register the supplied font file under a stable alias
    alias = None
    if fontfile:
        alias = _register_font_alias(doc, page, fontfile, alias="patrick_hand")

    # Use metrics from the file if possible
    font_obj = _font_object(None, fontfile)
    get_len = getattr(fitz, "get_text_length", None)

    def wlen(s: str) -> float:
        try:
            if font_obj and hasattr(font_obj, "text_length"):
                return float(font_obj.text_length(s, fontsize))
        except Exception:
            pass
        if get_len:
            try:
                return float(get_len(s, fontname="helv", fontsize=fontsize))
            except Exception:
                pass
        return 0.5 * fontsize * len(s)

    text = _sanitize_punct(text or "")
    if not text.strip():
        return 0

    # Simple wrapper using our width function
    max_w = max(1.0, rect.width)
    lines = []
    for para in (text.splitlines() or [""]):
        if not para:
            lines.append(""); continue
        words = para.split()
        cur = words[0] if words else ""
        for w in words[1:]:
            t = cur + " " + w
            if wlen(t) * float(tightness) <= max_w:
                cur = t
            else:
                lines.append(cur); cur = w
        lines.append(cur)

    y = rect.y0 + fontsize
    drawn = 0
    for ln in lines:
        if y > rect.y1:
            break
        try:
            if alias:  # preferred path: draw by *registered* font name
                page.insert_text(
                    fitz.Point(rect.x0, y), ln,
                    fontsize=fontsize,
                    color=color,
                    fontname=alias
                )
            elif fontfile:  # fallback: direct file (some builds ignore this)
                page.insert_text(
                    fitz.Point(rect.x0, y), ln,
                    fontsize=fontsize,
                    color=color,
                    fontfile=str(Path(fontfile).resolve())
                )
            else:          # last resort
                page.insert_text(
                    fitz.Point(rect.x0, y), ln,
                    fontsize=fontsize,
                    color=color
                )
        except TypeError:
            page.insert_text(fitz.Point(rect.x0, y), ln, fontsize=fontsize)
        drawn += len(ln)
        y += line_height_factor * fontsize

    if debug:
        print(f"[linedraw] alias={alias!r} drew ~{drawn} chars in {rect}")
    return drawn



def _draw_paragraph_textwriter(page, rect, text: str, *,
                               fontsize: float, color: Optional[Color],
                               fontname: Optional[str], fontfile: Optional[str],
                               tightness=0.96, line_height_factor=1.18,
                               debug: bool = False) -> int:
    """
    Draw wrapped text into 'rect' using TextWriter and a real TTF/OTF font.
    Super robust across older PyMuPDF versions.
    Returns number of characters drawn.
    """
    fitz = _import_fitz()
    font_obj = _font_object(fontname, fontfile)
    get_len_fallback = getattr(fitz, "get_text_length", None)

    inner_w = max(1.0, rect.width)
    text = _sanitize_punct(text or "")
    if not text.strip():
        if debug: print("[textwriter] empty text after sanitize")
        return 0

    lines, _ = _wrap_with_font_metrics(
        text, inner_w, fontsize, font_obj, get_len_fallback,
        tightness=tightness, line_height_factor=line_height_factor
    )
    if debug: print(f"[textwriter] lines={len(lines)} rect={rect}")

    # Try TextWriter first
    drawn = 0
    appended_any = False
    try:
        tw = fitz.TextWriter(page.rect)
    except Exception as e:
        if debug: print(f"[textwriter] cannot create TextWriter: {e}")
        tw = None

    y = rect.y0 + fontsize
    for ln in lines:
        if y > rect.y1:
            break
        appended = False
        if tw is not None:
            try:
                if font_obj is not None:
                    tw.append(fitz.Point(rect.x0, y), ln, font=font_obj,
                              fontsize=fontsize, color=color)
                else:
                    tw.append(fitz.Point(rect.x0, y), ln,
                              fontsize=fontsize, color=color)
                appended = True
            except Exception:
                try:
                    if font_obj is not None:
                        tw.append(fitz.Point(rect.x0, y), ln, font=font_obj,
                                  fontsize=fontsize)
                    else:
                        tw.append(fitz.Point(rect.x0, y), ln,
                                  fontsize=fontsize)
                    appended = True
                except Exception as e2:
                    if debug: print(f"[textwriter] append failed, fallback to insert_text: {e2}")

        if appended:
            drawn += len(ln); appended_any = True
        else:
            try:
                page.insert_text(
                    fitz.Point(rect.x0, y), ln,
                    fontsize=fontsize,
                    color=color,
                    fontname=(fontname or "helv")
                )
                drawn += len(ln)
            except Exception:
                page.insert_text(fitz.Point(rect.x0, y), ln, fontsize=fontsize)
                drawn += len(ln)

        y += line_height_factor * fontsize

    if tw is not None and appended_any:
        try:
            tw.write_text(page)
        except Exception as e:
            if debug: print(f"[textwriter] write_text failed: {e}")

    if debug:
        print(f"[textwriter] drew ~{drawn} chars in {rect}")
    return drawn

def _insert_textbox(page, rect, text: str, *,
                    fontsize: float,
                    color,
                    fontname: Optional[str] = None,
                    fontfile: Optional[Union[str, Path]] = None,
                    debug: bool = False,
                    prefer_textwriter: bool = False,
                    force_line_draw: bool = False) -> int:
    # If we absolutely need color+fontfile to apply, draw lines directly.
    if force_line_draw:
        return _draw_paragraph_lines(
            page, rect, _sanitize_punct(text),
            fontsize=fontsize, color=color,
            fontname=None,                      # name is resolved from registration
            fontfile=str(fontfile) if fontfile else None,
            tightness=0.96, line_height_factor=1.18,
            debug=debug
        )

    if prefer_textwriter:
        return _draw_paragraph_textwriter(
            page, rect, _sanitize_punct(text),
            fontsize=fontsize, color=color,
            fontname=fontname, fontfile=str(fontfile) if fontfile else None,
            tightness=0.96, line_height_factor=1.18,
            debug=debug
        )


    def _try_draw(txt: str, fs: float, use_name: Optional[str], use_file: Optional[Union[str, Path]]):
        try:
            kw = {"fontsize": fs, "align": 0}
            if color is not None: kw["color"] = color
            if use_name: kw["fontname"] = use_name
            if use_file is not None: kw["fontfile"] = str(use_file)
            n = page.insert_textbox(rect, txt, **kw)
            if debug:
                print(f"[insert_textbox] attempt fs={fs} name={use_name} file={use_file} -> {n}")
            return n
        except TypeError:
            try:
                kw = {"fontsize": fs, "align": 0}
                if color is not None: kw["color"] = color
                if use_name: kw["fontname"] = use_name
                n = page.insert_textbox(rect, txt, **kw)
                if debug:
                    print(f"[insert_textbox] legacy attempt fs={fs} name={use_name} -> {n}")
                return n
            except TypeError:
                return page.insertTextbox(rect, txt, fontsize=fs)

    n = _try_draw(text, fontsize, fontname, fontfile)
    if isinstance(n, (int, float)) and n > 0:
        return int(n)

    n = _try_draw(_sanitize_punct(text), fontsize, fontname, fontfile)
    if isinstance(n, (int, float)) and n > 0:
        return int(n)

    drawn = _draw_paragraph_textwriter(
        page, rect, _sanitize_punct(text),
        fontsize=fontsize, color=color,
        fontname=fontname, fontfile=str(fontfile) if fontfile else None,
        tightness=0.96, line_height_factor=1.18,
        debug=debug
    )
    return int(drawn)

def _draw_line(page, p0, p1, *, color: Optional[Color], width: float = 0.6):
    if color is None:
        return None
    try:
        return page.draw_line(p0, p1, color=color, width=width)
    except Exception:
        try:
            return page.drawLine(p0, p1, color=color, width=width)
        except Exception:
            return None

# ---------------- search, layout, collision helpers ----------------
def _dedup_rects(rect_like_list, round_ndigits=2):
    seen = set(); out = []
    for item in rect_like_list:
        rect = getattr(item, "rect", item)
        key = (round(rect.x0, round_ndigits), round(rect.y0, round_ndigits),
               round(rect.x1, round_ndigits), round(rect.y1, round_ndigits))
        if key not in seen:
            seen.add(key); out.append(item)
    return out

def _add_highlight(page, quads_or_rects):
    if hasattr(page, "add_highlight_annot"):
        return page.add_highlight_annot(quads_or_rects)
    if hasattr(page, "addHighlightAnnot"):
        return page.addHighlightAnnot(quads_or_rects)
    raise RuntimeError("This PyMuPDF version lacks highlight annotation API.")

# --- SIMPLE fallback wrap (kept as a fallback) -------------------
def _measure_height(text: str, width: float, fontsize: float):
    avg_char_w = 0.5 * fontsize
    max_chars = max(1, int(width / max(1e-3, avg_char_w)))
    lines = []
    for para in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(para, width=max_chars) or [""])
    line_h = 1.3 * fontsize
    return lines, max(2*fontsize, len(lines) * line_h)

# --- SMART METRIC-BASED WRAPPING + TIGHTNESS ---------------------
def _ensure_metrics_font(doc, fontname: Optional[str], fontfile: Optional[str]) -> str:
    """
    Return a font name for width measurements.
    If doc.insert_font exists, try to insert; otherwise just return name.
    Drawing will still pass fontfile directly in _insert_textbox.
    """
    use_name = fontname or "helv"
    if fontfile and hasattr(doc, "insert_font"):
        p = Path(fontfile)
        if p.exists():
            try:
                doc.insert_font(fontname=use_name, fontfile=str(p))
            except Exception:
                pass
    return use_name

def _measure_height_smart(text: str, width: float, fontsize: float,
                          metric_fontname: str,
                          line_height_factor: float = 1.18,
                          tightness: float = 0.96):
    """
    Wrap 'text' to fit 'width' using real font metrics when available.
    If get_text_length can't handle metric_fontname, fall back to base-14 names,
    else use the simple heuristic wrapper.
    """
    fitz = _import_fitz()
    get_len = getattr(fitz, "get_text_length", None)
    if get_len is None:
        return _measure_height(text, width, fontsize)

    max_w = max(1.0, float(width))
    probe_fonts = []
    if metric_fontname:
        probe_fonts.append(metric_fontname)
    probe_fonts.extend(["helv", "times", "courier"])

    use_font = None
    for fname in probe_fonts:
        try:
            _ = get_len("M", fontname=fname, fontsize=fontsize)
            use_font = fname
            break
        except Exception:
            continue

    if use_font is None:
        return _measure_height(text, width, fontsize)

    lines: List[str] = []

    def fits(s: str) -> bool:
        try:
            return get_len(s, fontname=use_font, fontsize=fontsize) * float(tightness) <= max_w
        except Exception:
            approx = 0.5 * fontsize * len(s)
            return approx <= max_w

    for para in (text.splitlines() or [""]):
        if not para:
            lines.append("")
            continue
        words = para.split()
        if not words:
            lines.append("")
            continue

        cur = words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if fits(trial):
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)

    line_h = line_height_factor * fontsize
    height = max(2 * fontsize, len(lines) * line_h)
    return lines, height

def _search_page(page, q: str, flags: int):
    try: return page.search_for(q, flags=flags, quads=True)
    except (TypeError, AttributeError): pass
    try: return page.search_for(q, flags=flags)
    except (TypeError, AttributeError): pass
    try: return page.search_for(q)
    except (TypeError, AttributeError): pass
    try: return page.searchFor(q, flags=flags)
    except (TypeError, AttributeError): pass
    try: return page.searchFor(q)
    except (TypeError, AttributeError): pass
    return []

def _text_rects_padded(fitz, page, pad=2.0):
    rects = []
    for b in page.get_text("blocks") or []:
        if len(b) >= 5 and (b[4] or "").strip():
            rects.append(fitz.Rect(b[0], b[1], b[2], b[3]) + (-pad, -pad, pad, pad))
    return rects

def _intersects_any(r, rects):
    for rr in rects:
        if r.intersects(rr): return True
    return False

def _blocks_index(fitz, page):
    out = []
    for i, b in enumerate(page.get_text("blocks") or []):
        if len(b) >= 4:
            out.append((i, fitz.Rect(b[0], b[1], b[2], b[3])))
    return out

def _block_for_rect_idx(fitz, page, rect, blocks_idx):
    r = getattr(rect, "rect", rect)
    center = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    best_idx, best_rect, best_area = None, None, -1.0
    for idx, br in blocks_idx:
        if br.contains(center) or br.intersects(r):
            inter = br & r
            area = inter.get_area() if inter is not None else 0.0
            if area >= best_area:
                best_idx, best_rect, best_area = idx, br, area
    if best_idx is None:
        pad = 3
        best_rect = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
        best_idx = -1
    return best_idx, best_rect

def _free_gaps_at_y(page, y_center: float, pad: float = 3.0, window: float = 12.0):
    words = page.get_text("words") or []
    intervals = []
    y_top = y_center - window; y_bot = y_center + window
    for w in words:
        wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
        if wy1 < y_top or wy0 > y_bot: continue
        intervals.append((wx0 - pad, wx1 + pad))
    intervals.sort()
    merged = []
    for x0, x1 in intervals:
        if not merged or x0 > merged[-1][1]:
            merged.append([x0, x1])
        else:
            merged[-1][1] = max(merged[-1][1], x1)
    L = page.rect.x0 + pad; R = page.rect.x1 - pad
    gaps = []; cur = L
    for x0, x1 in merged:
        if x0 > cur: gaps.append((max(L, cur), min(R, x0)))
        cur = max(cur, x1)
    if cur < R: gaps.append((cur, R))
    return gaps

def _choose_gap_for_y(page, blk_rect, cy, prefer_side, target_w, min_w):
    gaps = _free_gaps_at_y(page, cy)
    if not gaps: return None
    bx0, bx1 = blk_rect.x0, blk_rect.x1
    def dist(g):
        x0, x1 = g
        if x1 <= bx0: return bx0 - x1
        if x0 >= bx1: return x0 - bx1
        return 1e9
    ordered = sorted(gaps, key=lambda g: (dist(g), -(g[1]-g[0])))
    if prefer_side in ("left","right"):
        side_g = [g for g in ordered if (prefer_side=="left" and g[1]<=bx0) or (prefer_side=="right" and g[0]>=bx1)]
        if side_g: ordered = side_g
    for g in ordered:
        avail = g[1]-g[0]
        if avail >= (min_w + 6.0):
            final_w = min(target_w, max(min_w, avail - 6.0))
            return g, final_w
    return None

def _choose_gap_for_y_center_first(page, blk_rect, cy, prefer_side, target_w, min_w, page_box, center_tol):
    center_x = 0.5 * (page_box.x0 + page_box.x1)
    gaps = _free_gaps_at_y(page, cy)
    if not gaps:
        return None
    center_cands = []
    for g in gaps:
        midx = 0.5 * (g[0] + g[1])
        if abs(midx - center_x) <= float(center_tol):
            avail = g[1] - g[0]
            if avail >= (min_w + 6.0):
                final_w = min(target_w, max(min_w, avail - 6.0))
                center_cands.append((g, final_w))
    if center_cands:
        g, final_w = max(center_cands, key=lambda t: t[1])
        return g, final_w
    return _choose_gap_for_y(page, blk_rect, cy, prefer_side, target_w, min_w)

def _find_gap_nearby(page, blk_rect, cy0, prefer_side, target_w, min_w, page_box,
                     scan_step=8, max_scan=320, allow_center_gutter=False, center_tol=24.0):
    chooser = (lambda cy: _choose_gap_for_y_center_first(page, blk_rect, cy, prefer_side, target_w, min_w, page_box, center_tol)) \
              if allow_center_gutter else \
              (lambda cy: _choose_gap_for_y(page, blk_rect, cy, prefer_side, target_w, min_w))
    cand = chooser(cy0)
    if cand is not None:
        return cy0, cand
    for delta in range(scan_step, max_scan + scan_step, scan_step):
        for cy in (cy0 + delta, cy0 - delta):
            if cy <= page_box.y0 + 6 or cy >= page_box.y1 - 6:
                continue
            cand = chooser(cy)
            if cand is not None:
                return cy, cand
    return None, None

def _place_in_band(band_rect, y_center, w, h, placed: list, text_rects: list,
                   step=6, pad=3):
    if w > max(1.0, band_rect.width - 2*pad) or h > max(1.0, band_rect.height - 2*pad):
        return None
    def make(y_mid):
        y0 = max(band_rect.y0 + pad, y_mid - h/2)
        y1 = min(band_rect.y1 - pad, y0 + h); y0 = y1 - h
        return type(band_rect)(band_rect.x0 + pad, y0, band_rect.x0 + pad + w, y1)
    k = 0
    while k <= 2000:
        for sign in (+1, -1):
            y_mid = y_center + sign * k * step
            if y_mid < band_rect.y0 + pad or y_mid > band_rect.y1 - pad: continue
            cand = make(y_mid)
            if any(cand.intersects(r) for r in placed): continue
            if _intersects_any(cand, text_rects): continue
            return cand
        k += 1
    return None

# ---------------- variant-preserving expansion (case-insensitive) ------------
def _expand_variants_preserving(d: Dict[str, any]) -> Dict[str, any]:
    """Map each base key and its case-variants to the same value."""
    out = {}
    for k, v in d.items():
        for var in (k, k.lower(), k.upper(), k.title()):
            out.setdefault(var, v)
    return out

# ---------------- annotations JSON loader ----------------
def load_annotations_json(json_path: Union[str, Path]) -> List[Dict[str, str]]:
    p = Path(json_path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("Annotations JSON must be a list or a single object.")

    items: List[Dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        q = (row.get("quote") or row.get("query") or "").strip()
        if not q:
            continue
        items.append({
            "quote": q,
            "explanation": str(row.get("explanation", f"Note: {q}")),
            "color": row.get("color")
        })
    if not items:
        raise ValueError("No valid items found in annotations JSON.")
    return items

# ---------------- main ----------------
def highlight_and_margin_comment_pdf(
    pdf_path,
    queries,
    *,
    comments,
    out_path=None,
    highlight_color="yellow",
    note_fill="#FFFDE7",
    note_text="black",
    note_border="orange",
    note_opacity=0.0,
    note_fontsize=10.0,
    note_fontname="helv",
    note_fontfile=None,
    note_width=160.0,
    min_note_width=56.0,
    note_padding=4.0,
    note_border_width=1.0,
    draw_leader=True,
    leader_color="gray",
    case_sensitive=False,
    side="nearest",
    scan_step=8,
    max_scan=240,
    max_vertical_offset=72.0,
    within_block_pad=12.0,
    allow_column_footer=True,
    column_footer_max_offset=144.0,
    column_footer_top_gap=6.0,
    column_footer_side_pad=3.0,
    enable_fallback=False,
    fallback_zone="bottom",
    merge_duplicate_hits_tol=12.0,
    dedupe_note_y_tol=16.0,
    allow_center_gutter=False,
    center_gutter_tolerance=24.0,
    wrap_tightness=0.96,
    line_height_factor=1.18,
    annotations_json: Optional[Union[str, Path]] = None,
    dedupe_scope: str = "block",
    debug: bool = False,
    # --- new preview / override knobs ---
    plan_only: bool = False,
    fixed_note_rects: Optional[Dict[str, Tuple[float, float, float, float]]] = None,
    emit_callback=None,
):
    """
    When plan_only=False (default):
        returns (out_path:str, total_hits:int, total_notes:int, total_skipped:int)

    When plan_only=True:
        returns (None, total_hits:int, total_notes:int, total_skipped:int, placements:list)
        where each placement is a NotePlacement (if defined) or a lightweight object
        with attributes: uid, page_index, query, explanation, anchor_rect, note_rect,
                         leader_from, leader_to
    """
    # --- local helpers so this function is self-contained for preview support ---
    import hashlib
    fitz = _import_fitz()

    def _rect_tuple(r) -> Tuple[float, float, float, float]:
        rr = getattr(r, "rect", r)
        return (float(rr.x0), float(rr.y0), float(rr.x1), float(rr.y1))

    def _make_uid(page_index: int, norm_ct: str, cx: float, cy: float) -> str:
        base = f"{page_index}|{norm_ct}|{round(cx,2)}|{round(cy,2)}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

    # Fallback NotePlacement if caller hasn't defined one at module level
    NP = globals().get("NotePlacement")
    if NP is None:
        class _NP:
            __slots__ = ("uid","page_index","query","explanation",
                         "anchor_rect","note_rect","leader_from","leader_to")
            def __init__(self, **kw): 
                for k,v in kw.items(): setattr(self, k, v)
        NP = _NP  # type: ignore

    # ------------ normalize inputs (JSON-aware) ------------
    color_map_raw: Dict[str, Optional[str]] = {}

    if annotations_json is not None:
        items = load_annotations_json(annotations_json)
        qlist = [it["quote"] for it in items]
        comment_map = {it["quote"]: it["explanation"] for it in items}
        for it in items:
            color_map_raw[it["quote"]] = it.get("color")
    else:
        if isinstance(queries, str):
            qlist = [queries]
        else:
            qlist = [q for q in queries if isinstance(q, str) and q.strip()]
        if not qlist:
            raise ValueError("No valid queries.")
        if isinstance(comments, str):
            comment_map = {q: comments for q in qlist}
        else:
            comment_map = dict(comments)
            for q in qlist:
                comment_map.setdefault(q, f"Note: {q}")
        for q in qlist:
            color_map_raw[q] = str(highlight_color)

    # flags
    ci_flag = _pick_flag(fitz, ["TEXT_IGNORECASE", "TEXT_IGNORE_CASE"], None)
    dehy_flag = _pick_flag(fitz, ["TEXT_DEHYPHENATE"], 0)
    flags = 0
    if not case_sensitive and ci_flag is not None:
        flags |= ci_flag
    if dehy_flag:
        flags |= dehy_flag

    # Case-insensitive expansion when engine can't do it; PRESERVE colors/comments
    if not case_sensitive and ci_flag is None:
        comment_map   = _expand_variants_preserving(comment_map)
        color_map_raw = _expand_variants_preserving(color_map_raw)
        qlist = list(comment_map.keys())

    # colors
    default_hi = _parse_color(highlight_color)
    fill_rgb   = _parse_optional_color(note_fill)
    txt_rgb    = _parse_color(note_text)
    brd_rgb    = _parse_optional_color(note_border)
    lead_rgb   = _parse_optional_color(leader_color)

    def _resolve_hi(cand) -> Color:
        try:
            parsed = _parse_optional_color(cand)
        except Exception:
            parsed = None
        return parsed or default_hi

    per_highlight_color: Dict[str, Color] = {q: _resolve_hi(color_map_raw.get(q)) for q in qlist}

    pdf_path = Path(pdf_path)
    out_path = Path(out_path) if out_path else pdf_path.with_name(pdf_path.stem + "_annotated.pdf")
    doc = fitz.open(pdf_path)

    metric_fontname = _ensure_metrics_font(doc, note_fontname, note_fontfile)
    if debug:
        print(f"[font] metric_fontname={metric_fontname} file={note_fontfile}")

    total_hits = 0
    total_notes = 0
    total_skipped = 0
    doc_commented: set = set()

    placements: List[NP] = []  # type: ignore # collect in both modes if desired

    def _fallback_band(page):
        words = page.get_text("words") or []
        if not words:
            return None
        y_top = min(w[1] for w in words)
        y_bot = max(w[3] for w in words)
        pad = 8.0
        bands = []
        if fallback_zone in ("top", "both"):
            bands.append(fitz.Rect(page.rect.x0+pad, page.rect.y0+pad, page.rect.x1-pad, y_top-pad))
        if fallback_zone in ("bottom", "both"):
            bands.append(fitz.Rect(page.rect.x0+pad, y_bot+pad, page.rect.x1-pad, page.rect.y1-pad))
        bands = [b for b in bands if b.height >= 1.3*note_fontsize + 2*note_padding + 2]
        if not bands:
            return None
        bands.sort(key=lambda b: -b.height)
        return bands[0]

    for page in doc:
        page_box = page.rect
        blocks_idx = _blocks_index(fitz, page)
        text_rects = _text_rects_padded(fitz, page)
        placed = []
        anchors_by_comment = defaultdict(list)
        note_y_by_comment = defaultdict(list)
        page_commented: set = set()

        # hits
        page_hits = []
        for q in qlist:
            hits = _search_page(page, q, flags)
            if hits:
                hits = _dedup_rects(hits)
                page_hits.extend((q, h) for h in hits)
        if not page_hits:
            continue

        # highlight (per query color; set stroke+fill for compatibility)
        hits_by_query: Dict[str, List] = defaultdict(list)
        for q, h in page_hits:
            hits_by_query[q].append(h)
        for q, quads in hits_by_query.items():
            if not quads:
                continue
            quads = _dedup_rects(quads)
            annot = _add_highlight(page, quads)
            col = per_highlight_color.get(q, default_hi)
            if hasattr(annot, "set_colors"):
                try:
                    annot.set_colors(stroke=col, fill=col)
                except TypeError:
                    try:
                        annot.set_colors(stroke=col)
                    except TypeError:
                        pass
            if hasattr(annot, "set_opacity"):
                annot.set_opacity(0.25)
            if hasattr(annot, "update"):
                annot.update()
            total_hits += len(quads)

        commented = set()

        for q, hit in page_hits:
            r = getattr(hit, "rect", hit)
            cx0 = 0.5 * (r.x0 + r.x1)
            cy0 = 0.5 * (r.y0 + r.y1)

            blk_idx, blk_rect = _block_for_rect_idx(fitz, page, hit, blocks_idx)
            ctext = comment_map.get(q, f"Note: {q}")
            norm_ct = " ".join(ctext.split()).lower()
            key = (blk_idx, norm_ct)
            if key in commented:
                continue
            if any(abs(cy0 - py) <= merge_duplicate_hits_tol and abs(cx0 - px) <= merge_duplicate_hits_tol
                   for (px, py) in anchors_by_comment[norm_ct]):
                continue

            # De-dupe scope
            if dedupe_scope in ("page", "document"):
                if norm_ct in page_commented:
                    continue
                if dedupe_scope == "document" and norm_ct in doc_commented:
                    continue

            prefer = side if side != "nearest" else ("right" if (page_box.x1 - r.x1) <= (r.x0 - page_box.x0) else "left")

            cy_used, cand = _find_gap_nearby(
                page, blk_rect, cy0, prefer,
                note_width, min_note_width, page_box,
                scan_step=scan_step, max_scan=max_scan,
                allow_center_gutter=allow_center_gutter,
                center_tol=center_gutter_tolerance,
            )

            if cand is not None and cy_used is not None:
                too_far = abs(cy_used - cy0) > float(max_vertical_offset)
                out_of_block = not (blk_rect.y0 - within_block_pad <= cy_used <= blk_rect.y1 + within_block_pad)
                if too_far or out_of_block:
                    cand = None

            # footer fallback
            footer_pos = None
            footer_wrapped: Optional[List[str]] = None
            if cand is None and allow_column_footer:
                band_x0 = blk_rect.x0 + column_footer_side_pad
                band_x1 = blk_rect.x1 - column_footer_side_pad
                avail_w = max(0.0, band_x1 - band_x0)
                if avail_w >= (min_note_width + 6.0):
                    final_w = min(note_width, max(min_note_width, avail_w - 6.0))
                    footer_wrapped, inner_h = _measure_height_smart(
                        ctext, final_w - 2*note_padding, note_fontsize,
                        metric_fontname, line_height_factor=line_height_factor,
                        tightness=wrap_tightness
                    )
                    note_h = inner_h + 2*note_padding
                    band = fitz.Rect(band_x0, blk_rect.y1 + column_footer_top_gap,
                                     band_x1, page_box.y1 - 6.0)
                    footer_pos = _place_in_band(
                        band,
                        blk_rect.y1 + 0.5*note_h + column_footer_top_gap,
                        final_w, note_h, placed, text_rects, step=6, pad=3
                    )
                    if footer_pos is not None:
                        midy = 0.5 * (footer_pos.y0 + footer_pos.y1)
                        if abs(midy - cy0) > float(column_footer_max_offset):
                            footer_pos = None

            # ------------- function to finalize a placement (common path) -------------
            def _finalize_pos(pos_rect, wrapped_lines: Optional[List[str]] = None):
                nonlocal total_notes
                uid = _make_uid(int(page.number), norm_ct, cx0, cy0)

                # apply override if provided
                if fixed_note_rects and uid in fixed_note_rects:
                    pos = fitz.Rect(*fixed_note_rects[uid])
                else:
                    pos = pos_rect

                # preview/emit info about leader line
                leader_from = leader_to = None
                if draw_leader and lead_rgb is not None:
                    midy = 0.5 * (pos.y0 + pos.y1)
                    if pos.x1 <= blk_rect.x0:
                        leader_from = (float(pos.x1), float(midy))
                        leader_to   = (float(blk_rect.x0), float(midy))
                    elif pos.x0 >= blk_rect.x1:
                        leader_from = (float(pos.x0), float(midy))
                        leader_to   = (float(blk_rect.x1), float(midy))

                placement = NP(
                    uid=uid,
                    page_index=int(page.number),
                    query=q,
                    explanation=ctext,
                    anchor_rect=_rect_tuple(blk_rect),
                    note_rect=_rect_tuple(pos),
                    leader_from=leader_from,
                    leader_to=leader_to,
                )
                placements.append(placement)
                if emit_callback:
                    try:
                        emit_callback(placement)
                    except Exception:
                        pass

                # Bookkeeping shared by both modes
                placed.append(pos)
                total_notes += 1
                commented.add(key)
                note_y_by_comment[norm_ct].append(0.5 * (pos.y0 + pos.y1))
                anchors_by_comment[norm_ct].append((cx0, cy0))
                if dedupe_scope in ("page", "document"):
                    page_commented.add(norm_ct)
                    if dedupe_scope == "document":
                        doc_commented.add(norm_ct)

                if plan_only:
                    return  # don't draw anything

                # draw note rect
                _draw_note_box(page, pos, stroke_rgb=brd_rgb, fill_rgb=fill_rgb,
                               width=note_border_width, opacity=note_opacity)

                # draw text
                inner = pos + (note_padding, note_padding, -note_padding, -note_padding)
                tcol = per_highlight_color.get(q, txt_rgb)
                if wrapped_lines is None:
                    wrapped_lines, _inner_h = _measure_height_smart(
                        ctext, inner.width, note_fontsize,
                        metric_fontname, line_height_factor=line_height_factor,
                        tightness=wrap_tightness
                    )
                printed = _insert_textbox(
                    page, inner, "\n".join(wrapped_lines),
                    fontsize=note_fontsize,
                    color=tcol,
                    fontname=None,
                    fontfile=note_fontfile,
                    debug=debug,
                    force_line_draw=True
                )
                if debug and not printed:
                    print("[warn] printed 0 chars at", inner)

                # leader line (if any)
                if draw_leader and lead_rgb is not None:
                    midy = 0.5 * (pos.y0 + pos.y1)
                    if pos.x1 <= blk_rect.x0:
                        _draw_line(page, fitz.Point(pos.x1, midy), fitz.Point(blk_rect.x0, midy),
                                   color=lead_rgb, width=0.6)
                    elif pos.x0 >= blk_rect.x1:
                        _draw_line(page, fitz.Point(pos.x0, midy), fitz.Point(blk_rect.x1, midy),
                                   color=lead_rgb, width=0.6)

            # -------------------- choose where to place and finalize -------------------
            if cand is None and footer_pos is not None and footer_wrapped is not None:
                midy = 0.5 * (footer_pos.y0 + footer_pos.y1)
                if any(abs(midy - y) <= dedupe_note_y_tol for y in note_y_by_comment[norm_ct]):
                    total_skipped += 1
                    continue
                _finalize_pos(footer_pos, wrapped_lines=footer_wrapped)
                continue

            if cand is None and enable_fallback:
                band = _fallback_band(page)
                if band is not None:
                    avail = band.width
                    final_w = min(note_width, max(min_note_width, avail - 6.0))
                    wrapped, inner_h = _measure_height_smart(
                        ctext, final_w - 2*note_padding, note_fontsize,
                        metric_fontname, line_height_factor=line_height_factor,
                        tightness=wrap_tightness
                    )
                    note_h = inner_h + 2*note_padding
                    pos = _place_in_band(band, band.y0 + 0.5*band.height, final_w, note_h,
                                         placed, text_rects, step=6, pad=3)
                    if pos is not None:
                        midy = 0.5 * (pos.y0 + pos.y1)
                        if any(abs(midy - y) <= dedupe_note_y_tol for y in note_y_by_comment[norm_ct]):
                            total_skipped += 1
                            continue
                        _finalize_pos(pos, wrapped_lines=wrapped)
                        continue

            if cand is None:
                total_skipped += 1
                continue

            # side/gutter (or center-gutter) placement
            (gx0, gx1), final_w = cand
            wrapped, inner_h = _measure_height_smart(
                ctext, final_w - 2*note_padding, note_fontsize,
                metric_fontname, line_height_factor=line_height_factor,
                tightness=wrap_tightness
            )
            note_h = inner_h + 2*note_padding
            band = fitz.Rect(gx0, page_box.y0, gx1, page_box.y1)
            pos = _place_in_band(band, cy_used, final_w, note_h, placed, text_rects, step=6, pad=3)
            if pos is None:
                total_skipped += 1
                continue

            midy = 0.5 * (pos.y0 + pos.y1)
            if any(abs(midy - y) <= dedupe_note_y_tol for y in note_y_by_comment[norm_ct]):
                total_skipped += 1
                continue

            _finalize_pos(pos, wrapped_lines=wrapped)
            # end loop over hits

    # ---------- finalize ----------
    if not plan_only:
        doc.save(out_path, deflate=True, garbage=4)
        doc.close()
        return str(out_path), total_hits, total_notes, total_skipped
    else:
        doc.close()
        return None, total_hits, total_notes, total_skipped, placements




if __name__ == "__main__":
    saved, hi, notes, skipped = highlight_and_margin_comment_pdf(
        pdf_path="Myth.pdf",
        queries=[], comments={},
        annotations_json="myth.json",

        # Make more room so we don’t fight the fit
        note_width=240,            # wider than the default 160
        min_note_width=48,
        note_fontsize=9.0,

        # Visuals (no box, no leader)
        note_fill=None, note_border=None, note_border_width=0,
        note_text="red", draw_leader=False, leader_color=None,

        # Placement
        allow_column_footer=True,
        column_footer_max_offset=250,
        max_vertical_offset=90,
        max_scan=420,
        side="outer",
        allow_center_gutter=True,
        center_gutter_tolerance=48.0,

        # Dedupe per page so you get exactly two notes
        dedupe_scope="page",

        # Your font
        note_fontname="PatrickHand",
        note_fontfile=r".\fonts\PatrickHand-Regular.ttf",

        # Debug (to confirm fallback path)
        # debug=True,
    )
    print(f"Saved: {saved}  highlights={hi}  notes={notes}  skipped={skipped}")
