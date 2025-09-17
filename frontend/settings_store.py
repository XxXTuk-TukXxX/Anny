from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from .defaults import DEFAULTS


def _normalize_fontfile(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.startswith(".\\") or cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace("\\", "/")
    while "//" in cleaned and not cleaned.startswith("//"):
        cleaned = cleaned.replace("//", "/")
    return cleaned


def _settings_file() -> Path:
    """Return a writable path to persist user settings.

    On Windows, prefer %APPDATA%/Annotate/settings.json. Otherwise, use
    ~/.annotate_settings.json as a fallback.
    """
    try:
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "Annotate" / "settings.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    # Fallback in home directory
    p = Path.home() / ".annotate_settings.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def load_user_settings() -> Dict[str, Any]:
    """Load persisted settings, returning an empty dict on failure."""
    p = _settings_file()
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def save_user_settings(patch: Dict[str, Any]) -> bool:
    """Persist a partial settings dict, merging with existing file.

    Only keys present in DEFAULTS are accepted. Values are coerced to the
    type of the corresponding default when possible.
    """
    if not isinstance(patch, dict):
        return False
    current = load_user_settings()
    merged: Dict[str, Any] = {**current}
    for key, val in patch.items():
        if key not in DEFAULTS:
            continue
        default_val = DEFAULTS[key]
        try:
            # Coerce to the default's type where reasonable
            if isinstance(default_val, bool):
                merged[key] = bool(val)
            elif isinstance(default_val, int):
                merged[key] = int(val)
            elif isinstance(default_val, float):
                merged[key] = float(val)
            else:
                # Strings or other passthrough values
                merged[key] = val if val is not None else ""
            if key == "note_fontfile":
                merged[key] = _normalize_fontfile(merged[key])
        except Exception:
            # Skip invalid values, keep previous
            pass

    merged["note_fontname"] = DEFAULTS.get("note_fontname", "AnnotateNote")

    try:
        p = _settings_file()
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def reset_user_settings() -> bool:
    """Remove persisted settings file."""
    try:
        p = _settings_file()
        if p.exists():
            p.unlink()
        return True
    except Exception:
        return False


def get_effective_settings() -> Dict[str, Any]:
    """Defaults overlaid with any persisted user settings."""
    eff = dict(DEFAULTS)
    try:
        user = load_user_settings()
        for k, v in user.items():
            if k in eff:
                eff[k] = v
        eff["note_fontname"] = DEFAULTS.get("note_fontname", "AnnotateNote")
        eff["note_fontfile"] = _normalize_fontfile(eff.get("note_fontfile"))
    except Exception:
        pass
    return eff
