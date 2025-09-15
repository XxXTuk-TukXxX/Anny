import os
import shutil
from pathlib import Path
from typing import Optional
import sys
import subprocess

import ocrmypdf

# from modern_main import DEBUG

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
