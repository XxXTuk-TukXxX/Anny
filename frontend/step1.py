import threading
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .backend import run_ocr, _remove_background_supported


class Step1Mixin:
    """OCR step UI handlers."""

    # ---------- STEP 1: OCR ----------
    def _build_step1(self):
        pad = {"padx": 8, "pady": 6}

        tk.Label(self.step1, text="Input PDF:").grid(row=0, column=0, sticky="e", **pad)
        self.in_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.in_var, width=70).grid(row=0, column=1, **pad)
        ttk.Button(self.step1, text="Browse...", command=self._browse_in_pdf).grid(row=0, column=2, **pad)

        tk.Label(self.step1, text="OCR Output PDF:").grid(row=1, column=0, sticky="e", **pad)
        self.out_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.out_var, width=70).grid(row=1, column=1, **pad)
        ttk.Button(self.step1, text="Save As...", command=self._browse_out_pdf).grid(row=1, column=2, **pad)

        tk.Label(self.step1, text="Languages:").grid(row=2, column=0, sticky="e", **pad)
        self.lang_var = tk.StringVar(value="eng")
        tk.Entry(self.step1, textvariable=self.lang_var, width=20).grid(row=2, column=1, sticky="w", **pad)

        self.force_var = tk.BooleanVar(value=False)
        self.deskew_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=_remove_background_supported())
        self.optimize_var = tk.IntVar(value=0)

        ttk.Checkbutton(self.step1, text="Force OCR (re-OCR pages with text)", variable=self.force_var)\
            .grid(row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(self.step1, text="Deskew", variable=self.deskew_var)\
            .grid(row=4, column=1, sticky="w", **pad)
        self.clean_chk = ttk.Checkbutton(self.step1, text="Clean background", variable=self.clean_var)
        self.clean_chk.grid(row=5, column=1, sticky="w", **pad)
        if not _remove_background_supported():
            self.clean_var.set(False)
            self.clean_chk.state(["disabled"])
            ttk.Label(self.step1, text="(not supported by your OCRmyPDF version)", foreground="gray")\
                .grid(row=5, column=2, sticky="w", **pad)

        tk.Label(self.step1, text="Optimize (0–3):").grid(row=6, column=0, sticky="e", **pad)
        tk.Spinbox(self.step1, from_=0, to=3, textvariable=self.optimize_var, width=5)\
            .grid(row=6, column=1, sticky="w", **pad)

        tk.Label(self.step1, text="Tesseract path (optional):").grid(row=7, column=0, sticky="e", **pad)
        self.tess_var = tk.StringVar()
        tk.Entry(self.step1, textvariable=self.tess_var, width=70).grid(row=7, column=1, **pad)
        ttk.Button(self.step1, text="Find...", command=self._browse_tesseract).grid(row=7, column=2, **pad)

        self.ocr_status = tk.StringVar(value="Idle")
        tk.Label(self.step1, textvariable=self.ocr_status, fg="gray").grid(row=8, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 6))
        self.ocr_prog = ttk.Progressbar(self.step1, mode="indeterminate")
        self.ocr_prog.grid(row=9, column=0, columnspan=3, sticky="we", padx=12, pady=(0, 12))

        bar = ttk.Frame(self.step1)
        bar.grid(row=10, column=0, columnspan=3, sticky="e", padx=12, pady=(4, 12))
        ttk.Button(bar, text="Run OCR", command=self._run_ocr_clicked).pack(side="left", padx=6)
        ttk.Button(bar, text="Skip OCR → Next", command=lambda: self.nb.select(self.step2)).pack(side="left", padx=6)

    def _browse_in_pdf(self):
        p = filedialog.askopenfilename(title="Choose input PDF", filetypes=[("PDF files", "*.pdf")])
        if p:
            self.in_var.set(p)
            self.src_pdf = p
            if not self.out_var.get():
                self.out_var.set(str(Path(p).with_suffix(".ocr.pdf")))

    def _browse_out_pdf(self):
        p = filedialog.asksaveasfilename(
            title="Save OCR'd PDF as...",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if p:
            self.out_var.set(p)

    def _browse_tesseract(self):
        p = filedialog.askopenfilename(
            title="Locate Tesseract executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if p:
            self.tess_var.set(p)

    def _run_ocr_clicked(self):
        if not self.in_var.get().strip():
            messagebox.showwarning("Missing file", "Please choose an input PDF.")
            return

        self.ocr_status.set("Running OCR…")
        self.ocr_prog.start(10)

        def worker():
            try:
                outp = run_ocr(
                    input_pdf=self.in_var.get().strip(),
                    output_pdf=(self.out_var.get().strip() or None),
                    languages=(self.lang_var.get().strip() or "eng"),
                    force=self.force_var.get(),
                    optimize=int(self.optimize_var.get()),
                    deskew=self.deskew_var.get(),
                    clean=self.clean_var.get(),
                    custom_tesseract_path=(self.tess_var.get().strip() or None),
                )
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                self.after(0, lambda m=err_msg: self._ocr_done(error=m))
                return
            self.after(0, lambda p=str(outp): self._ocr_done(result=p))

        threading.Thread(target=worker, daemon=True).start()

    def _ocr_done(self, result: Optional[str] = None, error: Optional[str] = None):
        self.ocr_prog.stop()
        if error:
            self.ocr_status.set("Error")
            messagebox.showerror("OCR failed", error)
            return
        self.ocr_status.set("Done")
        self.ocr_pdf = result
        self.src_pdf = self.src_pdf or result
        messagebox.showinfo("Success", f"OCR complete:\n{result}\n\nProceed to Step 2.")
        self.nb.select(self.step2)