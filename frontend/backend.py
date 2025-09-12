import os
import shutil
from pathlib import Path
from typing import Optional

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
    return hasattr(ocrmypdf, "remove_background")


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
    )
    return out_path
