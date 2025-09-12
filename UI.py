from __future__ import annotations

from typing import Dict, Tuple, Optional

import tkinter as tk
from tkinter import ttk

from highlights import _import_fitz
from frontend.step1 import Step1Mixin
from frontend.step2 import Step2Mixin
from frontend.step3 import Step3Mixin



class WizardApp(tk.Tk, Step1Mixin, Step2Mixin, Step3Mixin):
    def __init__(self):
        super().__init__()
        self.title("PDF OCR → Annotate → Preview/Export (Exact)")
        self.geometry("1200x900")

        # State shared across steps
        self.src_pdf: Optional[str] = None  # original PDF chosen
        self.ocr_pdf: Optional[str] = None  # OCR output (if run)
        self.ann_json: Optional[str] = None  # annotations JSON
        self.fixed_overrides: Dict[str, Tuple[float, float, float, float]] = {}
        self.rotation_overrides: Dict[str, float] = {}
        self.placements = []  # plan-only placements
        self.color_map: Dict[str, str] = {}
        self.note_text_overrides: Dict[str, str] = {}
        self.note_fontsize_overrides: Dict[str, float] = {}
        self.ann_source_var = tk.StringVar(value="json")  # 'json' or 'gemini'
        self.g_txt_var = tk.StringVar()
        self.g_objective_var = tk.StringVar()
        self.g_model_var = tk.StringVar(value="gemini-2.5-flash")
        self.g_max_items_var = tk.IntVar(value=12)
        self.g_outfile_var = tk.StringVar()
        self._preview_pdf_path: Optional[str] = None
        self.doc = None
        self.page_imgs_ppm: Dict[int, bytes] = {}
        self.page_sizes: Dict[int, Tuple[int, int]] = {}
        self.cur_page = 0

        self.fitz = _import_fitz()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    # ---------- UI scaffold ----------
    def _build_ui(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.step1 = ttk.Frame(self.nb)
        self.step2 = ttk.Frame(self.nb)
        self.step3 = ttk.Frame(self.nb)

        self.nb.add(self.step1, text="1) OCR PDF")
        self.nb.add(self.step2, text="2) Annotation Settings")
        self.nb.add(self.step3, text="3) Preview (Exact) & Export")

        self._build_step1()
        self._build_step2()
        self._build_step3()


def main():
    app = WizardApp()
    app.mainloop()


if __name__ == "__main__":
    main()