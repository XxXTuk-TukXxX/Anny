import os
import shutil
from pathlib import Path
from typing import Optional
import sys
import subprocess

_DEFAULT_TESSERACT_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
)
_DEFAULT_GHOSTSCRIPT_PATHS = _DEFAULT_TESSERACT_PATHS


def _discover_bundled_tesseract() -> Optional[Path]:
    """Return path to bundled tesseract directory if present."""

    candidates: list[Path] = []
    exe = None
    try:
        exe = Path(sys.executable).resolve()
    except Exception:
        exe = None

    if getattr(sys, "frozen", False):
        if exe is not None:
            mac_resources = exe.parent.parent / "Resources" / "tesseract"
            candidates.append(mac_resources)
            candidates.append(exe.parent / "tesseract")
            candidates.append(exe.parent / "_internal" / "tesseract")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "tesseract")

    # Bundled macOS dependencies are not usable on Linux/Windows containers.
    if sys.platform == "darwin":
        here = Path(__file__).resolve().parent
        candidates.append(here.parent / "third_party" / "tesseract-macos")

    for base in candidates:
        try:
            bin_path = base / "bin" / "tesseract"
            if bin_path.exists():
                return base
        except Exception:
            continue
    return None


def _discover_bundled_ghostscript() -> Optional[Path]:
    """Return path to bundled ghostscript directory if present."""

    candidates: list[Path] = []
    exe = None
    try:
        exe = Path(sys.executable).resolve()
    except Exception:
        exe = None

    if getattr(sys, "frozen", False):
        if exe is not None:
            mac_resources = exe.parent.parent / "Resources" / "ghostscript"
            candidates.append(mac_resources)
            candidates.append(exe.parent / "ghostscript")
            candidates.append(exe.parent / "_internal" / "ghostscript")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "ghostscript")

    # Bundled macOS dependencies are not usable on Linux/Windows containers.
    if sys.platform == "darwin":
        here = Path(__file__).resolve().parent
        candidates.append(here.parent / "third_party" / "ghostscript-macos")

    for base in candidates:
        try:
            bin_path = base / "bin" / "gs"
            if bin_path.exists():
                return base
        except Exception:
            continue
    return None

import ocrmypdf

# from modern_main import DEBUG

def ensure_tesseract_available(custom_tesseract_path: str | None = None) -> None:
    bundle_root = _discover_bundled_tesseract()

    if custom_tesseract_path:
        p = Path(custom_tesseract_path)
        if not p.exists():
            raise FileNotFoundError(f"Tesseract not found at: {custom_tesseract_path}")
        os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
    elif bundle_root is not None:
        bin_dir = bundle_root / "bin"
        lib_dir = bundle_root / "lib"
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        share_dir = bundle_root / "share"
        tessdata_dir = share_dir / "tessdata"
        # Point Tesseract to the bundled language data; default to the share dir if tessdata missing.
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir if tessdata_dir.exists() else share_dir)
        dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
        os.environ["DYLD_LIBRARY_PATH"] = str(lib_dir) + os.pathsep + dyld if dyld else str(lib_dir)
    else:
        # When launched as a macOS .app, PATH is short; add common Homebrew locations.
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        missing = [p for p in _DEFAULT_TESSERACT_PATHS if p and p not in path_entries and Path(p).exists()]
        if missing:
            os.environ["PATH"] = os.pathsep.join(missing + path_entries)
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract is not available on PATH.\n\n"
            "Install Tesseract (e.g., UB Mannheim build on Windows) or pick its path "
            "in the 'Tesseract path' field."
        )


def _set_ghostscript_env(bundle_root: Optional[Path]) -> None:
    if bundle_root is None:
        return
    bin_dir = bundle_root / "bin"
    lib_dir = bundle_root / "lib"
    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{current_path}" if current_path else str(bin_dir)
    dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
    os.environ["DYLD_LIBRARY_PATH"] = f"{lib_dir}{os.pathsep}{dyld}" if dyld else str(lib_dir)

    share_root = bundle_root / "share" / "ghostscript"
    lib_paths: list[str] = []
    resource_dir: Optional[Path] = None
    if share_root.exists():
        versioned = sorted(
            (p for p in share_root.iterdir() if p.is_dir() and p.name[:1].isdigit()),
            key=lambda p: p.name,
            reverse=True,
        )
        target = versioned[0] if versioned else None
        if target:
            lib_candidate = target / "lib"
            resource_dir = target / "Resource"
            fonts_dir = target / "fonts"
            for path in (lib_candidate, resource_dir, resource_dir / "Init" if resource_dir else None, fonts_dir):
                if path and path.exists():
                    lib_paths.append(str(path))
        else:
            for fallback in ("lib", "Resource", "fonts"):
                candidate = share_root / fallback
                if candidate.exists():
                    lib_paths.append(str(candidate))
                    if fallback == "Resource":
                        resource_dir = candidate
    existing = os.environ.get("GS_LIB")
    if lib_paths:
        combined = os.pathsep.join(lib_paths + ([existing] if existing else []))
        os.environ["GS_LIB"] = combined
    if resource_dir and resource_dir.exists():
        resource_str = str(resource_dir)
        if not resource_str.endswith(os.sep):
            resource_str = resource_str + os.sep
        font_dir = resource_dir / "Font"
        font_str = str(font_dir)
        if not font_str.endswith(os.sep):
            font_str = font_str + os.sep
        os.environ.setdefault("GS_GEN_RESOURCE_DIR", resource_str)
        os.environ.setdefault("GS_RESOURCE_DIR", resource_str)
        os.environ.setdefault("GS_FONT_RESOURCE_DIR", font_str)
        gs_opts = os.environ.get("GS_OPTIONS", "")
        extra_opts = [
            f"-sGenericResourceDir={resource_str}",
            f"-sFontResourceDir={font_str}",
        ]
        opts = " ".join(extra_opts)
        os.environ["GS_OPTIONS"] = f"{gs_opts} {opts}".strip() if gs_opts else opts


def ensure_ghostscript_available() -> None:
    bundle_root = _discover_bundled_ghostscript()
    if bundle_root is not None:
        _set_ghostscript_env(bundle_root)
    else:
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        missing = [p for p in _DEFAULT_GHOSTSCRIPT_PATHS if p and p not in path_entries and Path(p).exists()]
        if missing:
            os.environ["PATH"] = os.pathsep.join(missing + path_entries)
    if shutil.which("gs") is None:
        raise RuntimeError(
            "Ghostscript ('gs') is not available on PATH.\n\n"
            "Install Ghostscript (brew install ghostscript) or bundle it under third_party/ghostscript-macos."
        )


def _remove_background_supported() -> bool:
    return hasattr(ocrmypdf, "remove_background")

# if DEBUG == True:
#     progress_bar = True
# else:
#     progress_bar = False

def run_ocr(
    input_pdf: str,
    output_pdf: Optional[str] = None,
    languages: str = "eng",
    force: bool = False,
    optimize: int = 0,
    deskew: bool = True,
    clean: bool = False,
    custom_tesseract_path: str | None = None,
) -> str:
    ensure_tesseract_available(custom_tesseract_path)
    ensure_ghostscript_available()
    out_path = output_pdf or str(Path(input_pdf).with_suffix(".ocr.pdf"))

    # Temporarily hide child consoles on Windows while running OCR pipeline.
    # Patch subprocess at runtime and also ocrmypdf's module tree to catch
    # "from subprocess import Popen" aliases.
    CREATE_NO_WINDOW = 0x08000000

    def _wrap_subprocess_call(fn):
        def _wrapped(*args, **kwargs):
            if sys.platform.startswith("win"):
                try:
                    cf = int(kwargs.get("creationflags", 0))
                except Exception:
                    cf = 0
                kwargs["creationflags"] = cf | CREATE_NO_WINDOW
                try:
                    si = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
                    si.dwFlags |= 0x00000001  # STARTF_USESHOWWINDOW
                    si.wShowWindow = 0  # SW_HIDE
                    kwargs["startupinfo"] = si
                except Exception:
                    pass
            return fn(*args, **kwargs)
        return _wrapped

    # Save originals
    _orig = {
        "Popen": subprocess.Popen,
        "run": getattr(subprocess, "run", None),
        "call": getattr(subprocess, "call", None),
        "check_call": getattr(subprocess, "check_call", None),
        "check_output": getattr(subprocess, "check_output", None),
    }

    # Apply wrappers to subprocess module
    subprocess.Popen = _wrap_subprocess_call(subprocess.Popen)  # type: ignore[assignment]
    if _orig["run"]:
        subprocess.run = _wrap_subprocess_call(_orig["run"])  # type: ignore[assignment]
    if _orig["call"]:
        subprocess.call = _wrap_subprocess_call(_orig["call"])  # type: ignore[assignment]
    if _orig["check_call"]:
        subprocess.check_call = _wrap_subprocess_call(_orig["check_call"])  # type: ignore[assignment]
    if _orig["check_output"]:
        subprocess.check_output = _wrap_subprocess_call(_orig["check_output"])  # type: ignore[assignment]

    # Also patch ocrmypdf module tree to catch direct imports of names
    patched_modules: list[tuple[object, str, object]] = []
    try:
        for name, mod in list(sys.modules.items()):
            if not name or not name.startswith("ocrmypdf"):
                continue
            try:
                # Replace attributes named like subprocess functions if present
                for attr in ("Popen", "run", "call", "check_call", "check_output"):
                    if hasattr(mod, attr):
                        orig = getattr(mod, attr)
                        wrapper = _wrap_subprocess_call(orig)
                        setattr(mod, attr, wrapper)
                        patched_modules.append((mod, attr, orig))
                # If module has a 'subprocess' attribute, wrap its functions too
                subm = getattr(mod, "subprocess", None)
                if subm is not None:
                    for attr in ("Popen", "run", "call", "check_call", "check_output"):
                        if hasattr(subm, attr):
                            orig = getattr(subm, attr)
                            wrapper = _wrap_subprocess_call(orig)
                            setattr(subm, attr, wrapper)
                            patched_modules.append((subm, attr, orig))
            except Exception:
                continue

        # Run OCR
        ocrmypdf.ocr(
        input_pdf,
        out_path,
        language=languages,
        force_ocr=force,
        # Skip pages that already contain text unless forcing re-OCR
        skip_text=not force,
        optimize=optimize,
        deskew=deskew,
        remove_background=clean,
        color_conversion_strategy="RGB",
        # Silence rich progress output in terminal
        progress_bar=False,
        )
    finally:
        # Restore subprocess
        try:
            subprocess.Popen = _orig["Popen"]  # type: ignore[assignment]
            if _orig["run"]:
                subprocess.run = _orig["run"]  # type: ignore[assignment]
            if _orig["call"]:
                subprocess.call = _orig["call"]  # type: ignore[assignment]
            if _orig["check_call"]:
                subprocess.check_call = _orig["check_call"]  # type: ignore[assignment]
            if _orig["check_output"]:
                subprocess.check_output = _orig["check_output"]  # type: ignore[assignment]
        except Exception:
            pass
        # Restore any patched attributes in ocrmypdf tree
        for target, attr, orig in patched_modules:
            try:
                setattr(target, attr, orig)
            except Exception:
                pass
    return out_path
