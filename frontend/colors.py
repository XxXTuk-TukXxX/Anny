import json
from pathlib import Path
from typing import Dict, Optional


def _tk_color(s: Optional[str], default: str = "#ff9800") -> str:
    if not s:
        return default
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        return s
    return s


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