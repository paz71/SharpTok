#!/usr/bin/env python3
"""
Cross-platform GUI for Sharp Pocket Computer BASIC tokenizer / detokenizer.

Wraps sharp_basic_v2.py. Requires Python 3 + tkinter (standard on most systems).

Usage:
    python3 sharp_basic_gui.py
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CORE_SCRIPT = SCRIPT_DIR / "sharp_basic_v2.py"

# ---------------------------------------------------------------------------
# Model list (mirrors MODEL_GROUPS in the core script)
# ---------------------------------------------------------------------------
MODELS = [
    # OLD / PC-125x family
    "1140", "1150",
    "1210", "1211", "1212",
    "1245", "1246", "1247", "1248", "1249",
    "1250", "1251", "1252", "1253", "1254", "1255",
    # NEW / NEW3
    "1100",
    "1260", "1261", "1262",
    "1350",
    "1401", "1402", "1403",
    "1425",
    "1430", "1431",
    "1440", "1445",
    "1450", "1460",
    # EXT
    "1280", "1360", "1470", "1475",
    # PC-1500 / 1600
    "1500", "1600",
    # E series
    "E500", "E550", "E650", "U6000", "1480", "1490",
    # G series
    "E200", "E220",
    "G801", "G802", "G803", "G805", "G811", "G813", "G815",
    "G820", "G830", "G850", "G850V",
]

DEFAULT_MODEL = "1403"


class SharpBasicGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SharpTok – Sharp Pocket Computer BASIC Tokenizer / Detokenizer")
        self.minsize(640, 520)
        self.geometry("780x600")

        # State
        self.mode = tk.StringVar(value="det")
        self.model = tk.StringVar(value="")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.running = False

        self._build_ui()
        self._on_mode_change()

        # Centre on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Mode
        mode_frm = ttk.LabelFrame(main, text="Mode", padding=8)
        mode_frm.pack(fill=tk.X, **pad)
        ttk.Radiobutton(
            mode_frm, text="Detokenize (binary → BASIC text)",
            variable=self.mode, value="det", command=self._on_mode_change
        ).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(
            mode_frm, text="Tokenize (BASIC text → binary)",
            variable=self.mode, value="tok", command=self._on_mode_change
        ).pack(side=tk.LEFT, padx=10)

        # Model
        model_frm = ttk.LabelFrame(main, text="Model", padding=8)
        model_frm.pack(fill=tk.X, **pad)
        self.model_label = ttk.Label(model_frm, text="Model:")
        self.model_label.pack(side=tk.LEFT)
        self.model_combo = ttk.Combobox(
            model_frm, textvariable=self.model, values=MODELS,
            width=12, state="normal"
        )
        self.model_combo.pack(side=tk.LEFT, padx=6)
        self.model_hint = ttk.Label(
            model_frm, text="", foreground="#555"
        )
        self.model_hint.pack(side=tk.LEFT, padx=8)

        # Files
        file_frm = ttk.LabelFrame(main, text="Files", padding=8)
        file_frm.pack(fill=tk.X, **pad)

        # Input
        ttk.Label(file_frm, text="Input:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(file_frm, textvariable=self.input_path, width=55).grid(
            row=0, column=1, sticky=tk.EW, padx=4
        )
        ttk.Button(file_frm, text="Browse…", command=self._browse_input).grid(
            row=0, column=2, padx=2
        )

        # Output
        self.out_label = ttk.Label(file_frm, text="Output:")
        self.out_label.grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.out_entry = ttk.Entry(file_frm, textvariable=self.output_path, width=55)
        self.out_entry.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=(6, 0))
        self.out_btn = ttk.Button(file_frm, text="Browse…", command=self._browse_output)
        self.out_btn.grid(row=1, column=2, padx=2, pady=(6, 0))

        self.out_hint = ttk.Label(
            file_frm, text="", foreground="#555"
        )
        self.out_hint.grid(row=2, column=1, sticky=tk.W, pady=(2, 0))

        file_frm.columnconfigure(1, weight=1)

        # Buttons
        btn_frm = ttk.Frame(main)
        btn_frm.pack(fill=tk.X, **pad)
        self.run_btn = ttk.Button(btn_frm, text="▶  Run", command=self._run)
        self.run_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frm, text="Clear log", command=self._clear_log).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frm, text="Quit", command=self.destroy).pack(
            side=tk.RIGHT, padx=4
        )

        # Log / result area
        log_frm = ttk.LabelFrame(main, text="Log / Result", padding=4)
        log_frm.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = scrolledtext.ScrolledText(
            log_frm, wrap=tk.WORD, height=18,
            font=("Consolas", 10) if sys.platform == "win32" else ("Menlo", 11)
            if sys.platform == "darwin" else ("DejaVu Sans Mono", 10)
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_configure("err", foreground="#c00")
        self.log.tag_configure("ok", foreground="#080")
        self.log.tag_configure("info", foreground="#06c")

        # Status
        self.status = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        # Check core script
        if not CORE_SCRIPT.is_file():
            self._log(f"ERROR: core script not found:\n  {CORE_SCRIPT}\n"
                      "Place sharp_basic_v2.py next to this GUI script.", "err")
            self.run_btn.configure(state=tk.DISABLED)

    def _on_mode_change(self) -> None:
        is_det = self.mode.get() == "det"
        if is_det:
            self.model_hint.configure(
                text="(optional – leave empty for auto-detect)"
            )
            self.model_combo.configure(state="normal")
            self.out_hint.configure(
                text="Optional. If empty, listing is shown in the log below."
            )
            # Always clear model in Detokenize mode so auto-detect is the default
            self.model.set("")
        else:
            self.model_hint.configure(text="(required)")
            self.model_combo.configure(state="readonly")
            if not self.model.get():
                self.model.set(DEFAULT_MODEL)
            self.out_hint.configure(text="Required – binary image will be written here.")

    # -------------------------------------------------------------- helpers
    def _browse_input(self) -> None:
        is_det = self.mode.get() == "det"
        if is_det:
            path = filedialog.askopenfilename(
                title="Select binary image",
                filetypes=[
                    ("Binary / Image", "*.bin *.img *.dat *.*"),
                    ("All files", "*.*"),
                ],
            )
        else:
            path = filedialog.askopenfilename(
                title="Select BASIC source",
                filetypes=[
                    ("BASIC text", "*.bas *.txt *.*"),
                    ("All files", "*.*"),
                ],
            )
        if path:
            self.input_path.set(path)
            # Suggest output name
            p = Path(path)
            if is_det and not self.output_path.get():
                self.output_path.set(str(p.with_suffix(".bas")))
            elif not is_det and not self.output_path.get():
                self.output_path.set(str(p.with_suffix(".bin")))

    def _browse_output(self) -> None:
        is_det = self.mode.get() == "det"
        if is_det:
            path = filedialog.asksaveasfilename(
                title="Save BASIC listing as",
                defaultextension=".bas",
                filetypes=[("BASIC text", "*.bas"), ("Text", "*.txt"), ("All", "*.*")],
            )
        else:
            path = filedialog.asksaveasfilename(
                title="Save binary image as",
                defaultextension=".bin",
                filetypes=[("Binary", "*.bin"), ("Image", "*.img"), ("All", "*.*")],
            )
        if path:
            self.output_path.set(path)

    def _log(self, msg: str, tag: str | None = None) -> None:
        self.log.insert(tk.END, msg + "\n", tag)
        self.log.see(tk.END)

    def _clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ----------------------------------------------------------------- run
    def _run(self) -> None:
        if self.running:
            return

        inp = self.input_path.get().strip()
        out = self.output_path.get().strip()
        model = self.model.get().strip()
        is_det = self.mode.get() == "det"

        if not inp:
            messagebox.showerror("Missing input", "Please select an input file.")
            return
        if not Path(inp).is_file():
            messagebox.showerror("File not found", f"Input file does not exist:\n{inp}")
            return
        if not is_det and not out:
            messagebox.showerror("Missing output", "Tokenize requires an output file.")
            return
        if not is_det and not model:
            messagebox.showerror("Missing model", "Tokenize requires a model selection.")
            return

        # Build command
        cmd = [sys.executable, str(CORE_SCRIPT)]
        if is_det:
            cmd.append("det")
            if model:
                cmd += ["--model", model]
            cmd.append(inp)
            if out:
                cmd.append(out)
        else:
            cmd += ["tok", "--model", model, inp, out]

        self._clear_log()
        self._log("Command: " + " ".join(cmd), "info")
        self._log("-" * 60)
        self.running = True
        self.run_btn.configure(state=tk.DISABLED)
        self._set_status("Running…")

        threading.Thread(target=self._execute, args=(cmd, is_det, out), daemon=True).start()

    def _execute(self, cmd: list[str], is_det: bool, out: str) -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = proc.communicate(timeout=60)

            def finish() -> None:
                if stderr:
                    self._log(stderr.rstrip(), "err" if proc.returncode else "info")
                if stdout:
                    self._log(stdout.rstrip())
                if proc.returncode == 0:
                    self._log("\n✓ Finished successfully.", "ok")
                    if not is_det and out:
                        self._log(f"Binary written to: {out}", "ok")
                    elif is_det and out:
                        self._log(f"Listing written to: {out}", "ok")
                else:
                    self._log(f"\n✗ Exit code {proc.returncode}", "err")
                self.running = False
                self.run_btn.configure(state=tk.NORMAL)
                self._set_status("Ready" if proc.returncode == 0 else "Error")

            self.after(0, finish)

        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._fail("Process timed out (60 s)."))
        except Exception as exc:
            self.after(0, lambda: self._fail(str(exc)))

    def _fail(self, msg: str) -> None:
        self._log(f"ERROR: {msg}", "err")
        self.running = False
        self.run_btn.configure(state=tk.NORMAL)
        self._set_status("Error")


def main() -> None:
    # High-DPI awareness on Windows
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = SharpBasicGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
