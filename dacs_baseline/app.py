from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .user_settings import load_settings, needs_setup, save_settings


def _repo_root() -> Path:
    # Frozen exe: folder containing the exe. Dev: package parent.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _python_exe(root: Path) -> Path:
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return venv
    return Path(sys.executable)


class SetupDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, root: Path):
        super().__init__(master)
        self.title("DACS Baseline — First-time setup")
        self.resizable(True, True)
        self.root = root
        self.settings = load_settings(root)
        self.result: dict | None = None

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(
            frm,
            text=(
                "Customize paths for this computer. These are saved to "
                "user-settings.json next to the app."
            ),
            wraplength=520,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.vars: dict[str, tk.StringVar] = {}
        fields = [
            ("work_dir", "Working folder (app root)"),
            ("input_dir", "Identifier files folder"),
            ("reports_dir", "Reports folder"),
            ("user_data_dir", "Chrome profile folder"),
            ("efts_url", "EFTS URL"),
            ("default_label", "Default run label"),
            ("delay_seconds", "Delay between items (seconds)"),
            ("batch_size", "Batch size (0 = off)"),
            ("batch_pause_seconds", "Batch pause (seconds)"),
            ("midrun_cac_timeout_seconds", "Mid-run CAC wait (seconds)"),
            ("details_tab_timeout_seconds", "Details tab populate wait (seconds)"),
        ]
        for i, (key, label) in enumerate(fields, start=1):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(self.settings.get(key, "")))
            self.vars[key] = var
            entry = ttk.Entry(frm, textvariable=var, width=58)
            entry.grid(row=i, column=1, sticky="ew", pady=3, padx=6)
            if key.endswith("_dir") or key in {"work_dir", "input_dir", "reports_dir", "user_data_dir"}:
                ttk.Button(
                    frm,
                    text="Browse…",
                    command=lambda k=key: self._browse_dir(k),
                ).grid(row=i, column=2, sticky="w")

        frm.columnconfigure(1, weight=1)
        btns = ttk.Frame(frm)
        btns.grid(row=len(fields) + 1, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save & Continue", command=self._save).pack(side="right")

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _browse_dir(self, key: str) -> None:
        initial = self.vars[key].get() or str(self.root)
        chosen = filedialog.askdirectory(initialdir=initial, parent=self)
        if chosen:
            self.vars[key].set(chosen)

    def _save(self) -> None:
        data = dict(self.settings)
        for key, var in self.vars.items():
            raw = var.get().strip()
            if key in {
                "delay_seconds",
                "batch_pause_seconds",
            }:
                data[key] = float(raw or 0)
            elif key in {
                "batch_size",
                "midrun_cac_timeout_seconds",
                "details_tab_timeout_seconds",
                "cac_timeout_seconds",
                "navigation_timeout_seconds",
            }:
                data[key] = int(float(raw or 0))
            else:
                data[key] = raw
        data["setup_complete"] = True
        work = Path(data["work_dir"])
        work.mkdir(parents=True, exist_ok=True)
        for key in ("input_dir", "reports_dir", "user_data_dir"):
            Path(data[key]).mkdir(parents=True, exist_ok=True)
        save_settings(data, work)
        # Also keep a copy next to the launcher if work_dir differs
        if work.resolve() != self.root.resolve():
            save_settings(data, self.root)
        self.result = data
        self.destroy()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DACS DD1348 Baseline Scanner")
        self.geometry("720x640")
        self.root_dir = _repo_root()
        os.chdir(self.root_dir)

        if needs_setup(self.root_dir):
            dlg = SetupDialog(self, self.root_dir)
            self.wait_window(dlg)
            if not dlg.result:
                self.destroy()
                return

        self.settings = load_settings(self.root_dir)
        work = Path(self.settings.get("work_dir") or self.root_dir)
        if work.exists():
            os.chdir(work)
            self.root_dir = work
            self.settings = load_settings(work)

        self._build()

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="DACS Original DD1348 Baseline", font=("", 14, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            frm,
            text="Choose options, then Start Scan. Close Excel report files first to avoid permission errors.",
            wraplength=680,
        ).pack(anchor="w", pady=(0, 8))

        grid = ttk.Frame(frm)
        grid.pack(fill="x")

        self.label_var = tk.StringVar(value=str(self.settings.get("default_label", "before")))
        self.input_var = tk.StringVar(
            value=str(Path(self.settings["input_dir"]) / "identifiers-full-462.txt")
        )
        self.lines_var = tk.StringVar(value="")
        self.skip_var = tk.StringVar(value="")
        self.max_var = tk.StringVar(value="")
        self.delay_var = tk.StringVar(value=str(self.settings.get("delay_seconds", 2)))
        self.batch_var = tk.StringVar(value=str(self.settings.get("batch_size", 25)))
        self.pause_var = tk.StringVar(
            value=str(self.settings.get("batch_pause_seconds", 45))
        )
        self.pick_var = tk.BooleanVar(value=True)

        rows = [
            ("Run label", self.label_var, None),
            ("Input file", self.input_var, self._browse_input),
            ("Lines to run (e.g. 5-8 or 1,3,10)", self.lines_var, None),
            ("Skip lines (e.g. 2,4)", self.skip_var, None),
            ("Max count (optional)", self.max_var, None),
            ("Delay seconds", self.delay_var, None),
            ("Batch size", self.batch_var, None),
            ("Batch pause seconds", self.pause_var, None),
        ]
        for i, (label, var, browse) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", **pad)
            ttk.Entry(grid, textvariable=var, width=55).grid(
                row=i, column=1, sticky="ew", **pad
            )
            if browse:
                ttk.Button(grid, text="Browse…", command=browse).grid(
                    row=i, column=2, **pad
                )
        grid.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            frm, text="Open file picker before scan", variable=self.pick_var
        ).pack(anchor="w", pady=6)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Setup / Paths…", command=self._reopen_setup).pack(
            side="left"
        )
        ttk.Button(btns, text="Start Scan", command=self._start).pack(side="right")
        ttk.Button(btns, text="Quit", command=self.destroy).pack(side="right", padx=6)

        ttk.Label(frm, text="Log").pack(anchor="w")
        self.log = tk.Text(frm, height=18, wrap="word")
        self.log.pack(fill="both", expand=True)

    def _browse_input(self) -> None:
        initial = self.settings.get("input_dir") or str(self.root_dir / "input")
        path = filedialog.askopenfilename(
            initialdir=initial,
            filetypes=[
                ("Identifier lists", "*.txt;*.csv;*.xlsx"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            self.pick_var.set(False)

    def _reopen_setup(self) -> None:
        dlg = SetupDialog(self, self.root_dir)
        self.wait_window(dlg)
        if dlg.result:
            self.settings = dlg.result
            work = Path(self.settings["work_dir"])
            if work.exists():
                os.chdir(work)
                self.root_dir = work

    def _append(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")

    def _start(self) -> None:
        args = self._build_args()
        self._append(f"> {' '.join(args)}\n")
        thread = threading.Thread(target=self._run, args=(args,), daemon=True)
        thread.start()

    def _build_args(self) -> list[str]:
        py = str(_python_exe(self.root_dir))
        args = [
            py,
            "-m",
            "dacs_baseline",
            "scan",
            "--label",
            self.label_var.get().strip() or "before",
            "--delay-seconds",
            self.delay_var.get().strip() or "2",
            "--batch-size",
            self.batch_var.get().strip() or "0",
            "--batch-pause-seconds",
            self.pause_var.get().strip() or "30",
            "--efts-url",
            str(self.settings.get("efts_url", "")),
            "--out-dir",
            str(self.settings.get("reports_dir", "reports/dd1348-irrd")),
            "--user-data-dir",
            str(self.settings.get("user_data_dir", "user-data")),
            "--midrun-cac-timeout-seconds",
            str(self.settings.get("midrun_cac_timeout_seconds", 300)),
            "--details-tab-timeout-seconds",
            str(self.settings.get("details_tab_timeout_seconds", 300)),
            "--cac-timeout-seconds",
            str(self.settings.get("cac_timeout_seconds", 600)),
            "--navigation-timeout-seconds",
            str(self.settings.get("navigation_timeout_seconds", 300)),
        ]
        if self.pick_var.get():
            args.append("--pick-input")
        else:
            args.extend(["--no-pick-input", "--input", self.input_var.get().strip()])
        lines = self.lines_var.get().strip()
        if lines:
            args.extend(["--lines", lines])
        skip = self.skip_var.get().strip()
        if skip:
            args.extend(["--skip-lines", skip])
        mx = self.max_var.get().strip()
        if mx:
            args.extend(["--max", mx])
        return args

    def _run(self, args: list[str]) -> None:
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(self.root_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.after(0, self._append, line)
            code = proc.wait()
            self.after(0, self._append, f"\n[exit {code}]\n")
            if code == 0:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Scan complete",
                        "Scan finished. Check the reports folder and summary.txt.",
                    ),
                )
        except Exception as exc:
            self.after(0, self._append, f"ERROR: {exc}\n")
            self.after(0, lambda: messagebox.showerror("Scan failed", str(exc)))


def main() -> int:
    app = App()
    if app.winfo_exists():
        app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
