# Backend helpers for OCR-ing PDFs with OCRmyPDF.
# Requires: pip install ocrmypdf
# External dependency: Tesseract OCR must be installed and on PATH (or pass its path).

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

import ocrmypdf

__all__ = ["ensure_tesseract_available", "run_ocr"]


def ensure_tesseract_available(custom_tesseract_path: str | None = None) -> None:
    """
    Ensure 'tesseract' is available on PATH.
    If a full path to tesseract executable is provided, prepend its folder to PATH.
    """
    if custom_tesseract_path:
        p = Path(custom_tesseract_path)
        if not p.exists():
            raise FileNotFoundError(f"Tesseract not found at: {custom_tesseract_path}")
        os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")

    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract is not available on PATH.\n\n"
            "Install Tesseract (e.g., UB Mannheim build on Windows) and/or set its path "
            "in the GUI field (e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe)."
        )


def run_ocr(
    input_pdf: str,
    output_pdf: str | None = None,
    languages: str = "eng",
    force: bool = False,
    jobs: int | None = None,
    optimize: int = 0,
    deskew: bool = True,
    clean: bool = True,
    custom_tesseract_path: str | None = None,
) -> Path:
    """
    Perform OCR on a PDF and return the output Path.
    - Adds a searchable (invisible) text layer to each page.
    - Uses Tesseract via OCRmyPDF.

    Args:
        input_pdf: Path to input PDF.
        output_pdf: Desired output path; defaults to <input>.ocr.pdf.
        languages: Tesseract language(s), e.g. "eng" or "eng+lit".
        force: Re-OCR even if text is already detected.
        jobs: Parallel jobs (None = auto).
        optimize: 0..3; higher compresses more (slower).
        deskew: Attempt to deskew pages.
        clean: Remove background artifacts.
        custom_tesseract_path: Full path to tesseract binary if not on PATH.

    Returns:
        Path to the OCR’d PDF.
    """
    ensure_tesseract_available(custom_tesseract_path)

    in_path = Path(input_pdf)
    if not in_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {in_path}")

    out_path = Path(output_pdf) if output_pdf else in_path.with_suffix(".ocr.pdf")

    ocrmypdf.ocr(
        input_file=str(in_path),
        output_file=str(out_path),
        language=languages,
        force_ocr=force,            # re-OCR even if text exists
        skip_text=not force,        # default: skip pages that already have text
        rotate_pages=True,
        rotate_pages_threshold=14.0,
        deskew=deskew,
        remove_background=clean,
        optimize=optimize,
        jobs=jobs,
        progress_bar=False,
    )
    return out_path