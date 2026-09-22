"""Native daily-use interface for the isolated Geforce NR launcher.

The module is intentionally safe to import: it does not import tkinter, create a
window, acquire the single-instance mutex, or initialize the backend until
``main()`` is called.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from typing import Any


APP_TITLE = "Geforce NR"
APP_DIR = Path(__file__).resolve().parent
ERROR_LOG = APP_DIR / "daily-ui-error.log"
POLL_INTERVAL_MS = 500
# Keep the existing singleton ID across branding changes.
MUTEX_NAME = r"Local\GFNHUDGuardDailyUI"

RECOMMENDED_SETTINGS: dict[str, Any] = {
    "nr_height": 720,
    "flow_width": 1280,
    "flow_grid": 2,
    "flow_preset": "fast",
    "mode": "nr",
    "mask_profile": "custom",
}

MODE_LABELS = {
    "NR — Neural Rendering": "nr",
    "Bypass — capture only": "bypass",
}
MODE_VALUES_TO_LABELS = {value: label for label, value in MODE_LABELS.items()}
MASK_LABELS = {'Custom regions (selected game)': 'custom', 'Cyberpunk 2077 preset (1440p)': 'cyberpunk'}


def fit_window_bounds(requested, work_area, decoration=(0, 0)):
    left, top, right, bottom = work_area
    dw, dh = decoration
    width = max(1, min(requested[0], right-left-dw))
    height = max(1, min(requested[1], bottom-top-dh))
    return width, height, left+max(0, (right-left-width-dw)//2), top+max(0, (bottom-top-height-dh)//2)


def _write_error_log(context: str) -> None:
    """Replace the local diagnostic log with the current exception traceback."""
    try:
        ERROR_LOG.write_text(
            f"{context}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except OSError:
        # Logging must never hide the original startup/runtime exception.
        pass


def _show_startup_error(message: str) -> None:
    """Show an error without requiring a functioning Tk interpreter."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                message,
                f"{APP_TITLE} — Startup error",
                0x00000010,
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        # Per-monitor-v2 awareness keeps ttk text and controls sharp if the
        # window moves between monitors with different scaling factors.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


class SingleInstanceGuard:
    """Own a Windows named mutex and focus the existing window on duplicates."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        self._handle: int | None = None
        self.already_running = False
        if sys.platform != "win32":
            return

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        create_error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(create_error)
        self._handle = handle
        self.already_running = create_error == self.ERROR_ALREADY_EXISTS
        if self.already_running:
            # The first process may hold the mutex just before its Tk window is
            # mapped. A bounded retry still leaves duplicate launches quick.
            for _attempt in range(10):
                if self.focus_existing_window():
                    break
                time.sleep(0.1)

    @staticmethod
    def focus_existing_window() -> bool:
        if sys.platform != "win32":
            return False
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            return True
        return False

    def close(self) -> None:
        if self._handle and sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(self._handle)
            self._handle = None


class DailyApp:
    """Single-window tkinter/ttk UI backed by ``DailyController``."""

    def __init__(self, root: Any, controller: Any) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.root = root
        self.controller = controller
        self.targets: list[dict[str, Any]] = []
        self.target_by_display: dict[str, dict[str, Any]] = {}
        self._closing = False
        self._stop_requested_for_close = False
        self._last_state = "idle"
        self._run_path: Path | None = None
        self._mask_ready = True

        self.root.title(APP_TITLE)
        self.root.geometry("800x620")
        self.root.configure(background="#111a1d")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._configure_style()
        self._create_variables()
        self._build_ui()
        self._load_settings()
        self.refresh_targets()
        self._set_status(
            state="idle",
            detail="Choose the GeForce NOW game window, then start the guard.",
            geometry="Not running",
            nr_confirmed=False,
            hardware_flow_active=False,
            run=None,
        )
        self._fit_window_to_work_area()
        self.root.after(POLL_INTERVAL_MS, self._poll_controller)

    def _fit_window_to_work_area(self) -> None:
        """Fit the fully measured ttk layout without exceeding the work area."""
        self.root.update_idletasks()
        requested_width = max(800, self.root.winfo_reqwidth())
        requested_height = max(620, self.root.winfo_reqheight())
        available_width = self.root.winfo_screenwidth()
        available_height = self.root.winfo_screenheight()
        left = top = 0
        decoration = (0, 0)

        if sys.platform == "win32":
            class Rect(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.SystemParametersInfoW.argtypes = [
                    wintypes.UINT,
                    wintypes.UINT,
                    wintypes.LPVOID,
                    wintypes.UINT,
                ]
                user32.SystemParametersInfoW.restype = wintypes.BOOL
                work_area = Rect()
                if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0):
                    left, top = work_area.left, work_area.top
                    available_width = work_area.right - work_area.left
                    available_height = work_area.bottom - work_area.top
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
                user32.GetWindowRect.restype = wintypes.BOOL
                outer = Rect()
                wrapper = user32.GetAncestor(self.root.winfo_id(), 2)
                if wrapper and user32.GetWindowRect(wrapper, ctypes.byref(outer)):
                    decoration = (max(0, outer.right-outer.left-self.root.winfo_width()),
                                  max(0, outer.bottom-outer.top-self.root.winfo_height()))
            except Exception:
                pass

        width, height, x, y = fit_window_bounds((requested_width, requested_height),
            (left, top, left+available_width, top+available_height), decoration)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(720, width), min(requested_height, height))

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass

        bg = "#111a1d"
        panel = "#192529"
        panel_alt = "#213137"
        text = "#edf4f2"
        muted = "#aebdb9"
        green = "#4fd18b"
        green_active = "#69dea0"
        border = "#385057"

        style.configure("App.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("Header.TLabel", background=bg, foreground=text, font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=panel, foreground=text, font=("Segoe UI Semibold", 11))
        style.configure("Body.TLabel", background=panel, foreground=text, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Value.TLabel", background=panel_alt, foreground=text, font=("Segoe UI Semibold", 10), padding=(10, 7))
        style.configure("State.TLabel", background=panel, foreground=green, font=("Segoe UI Semibold", 15))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Primary.TButton", background=green, foreground="#0a2116", bordercolor=green, font=("Segoe UI Semibold", 12), padding=(18, 12))
        style.map("Primary.TButton", background=[("active", green_active), ("disabled", "#425851")], foreground=[("disabled", "#96a29f")])
        style.configure("Stop.TButton", background="#d66b66", foreground="#1f0c0b", bordercolor="#d66b66", font=("Segoe UI Semibold", 12), padding=(18, 12))
        style.map("Stop.TButton", background=[("active", "#e27d78"), ("disabled", "#544646")], foreground=[("disabled", "#a99c9b")])
        style.configure("TCombobox", fieldbackground="#26383e", background="#26383e", foreground=text, arrowcolor=text, bordercolor=border, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", "#26383e"), ("disabled", "#1b292d")], foreground=[("readonly", text), ("disabled", "#71817d")])
        style.configure("TRadiobutton", background=panel, foreground=text, font=("Segoe UI", 9))
        style.map("TRadiobutton", background=[("active", panel)], foreground=[("disabled", "#71817d")])
        style.configure("TSeparator", background=border)
        style.configure('TCheckbutton', background=panel, foreground=text, font=('Segoe UI', 10))
        style.map('TCheckbutton', background=[('active', panel)], foreground=[('disabled', '#71817d')])

    def _create_variables(self) -> None:
        self.target_var = self.tk.StringVar()
        self.mode_var = self.tk.StringVar()
        self.mask_enabled_var = self.tk.BooleanVar(value=False)
        self.mask_profile_var = self.tk.StringVar()
        self.mask_summary_var = self.tk.StringVar()
        self.nr_height_var = self.tk.IntVar()
        self.flow_width_var = self.tk.IntVar()
        self.flow_grid_var = self.tk.IntVar()
        self.flow_preset_var = self.tk.StringVar()
        self.status_state_var = self.tk.StringVar(value="IDLE")
        self.status_detail_var = self.tk.StringVar()
        self.geometry_var = self.tk.StringVar(value="Not running")
        self.nr_status_var = self.tk.StringVar(value="Not confirmed")
        self.flow_status_var = self.tk.StringVar(value="Inactive")

    def _build_ui(self) -> None:
        outer = self.ttk.Frame(self.root, style="App.TFrame", padding=(24, 16, 24, 14))
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = self.ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.ttk.Label(header, text=APP_TITLE, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        self.ttk.Label(
            header,
            text="Neural Rendering with optional, user-drawn HUD protection",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        target_panel = self.ttk.Frame(outer, style="Panel.TFrame", padding=12)
        target_panel.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        target_panel.columnconfigure(0, weight=1)
        self.ttk.Label(target_panel, text="Game window", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.target_combo = self.ttk.Combobox(target_panel, textvariable=self.target_var, state="readonly")
        self.target_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.target_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_mask_status())
        self.refresh_button = self.ttk.Button(target_panel, text="Refresh", command=self.refresh_targets)
        self.refresh_button.grid(row=1, column=1, sticky="e")

        controls = self.ttk.Frame(outer, style="Panel.TFrame", padding=12)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(0, weight=3)
        controls.columnconfigure(1, weight=2)
        controls.columnconfigure(2, weight=2)

        self.ttk.Label(controls, text="Mode", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 7))
        self.mode_combo = self.ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=tuple(MODE_LABELS),
            state="readonly",
        )
        self.mode_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.mode_combo.bind('<<ComboboxSelected>>', lambda _event: self._refresh_mask_status())

        self.start_button = self.ttk.Button(controls, text="Start", style="Primary.TButton", command=self.start)
        self.start_button.grid(row=1, column=1, sticky="ew", padx=(0, 5))
        self.stop_button = self.ttk.Button(controls, text="Stop safely", style="Stop.TButton", command=self.stop)
        self.stop_button.grid(row=1, column=2, sticky="ew", padx=(5, 0))

        self.mask_check = self.ttk.Checkbutton(controls, text='Enable HUD Mask (optional)',
            variable=self.mask_enabled_var, command=self._refresh_mask_status)
        self.mask_check.grid(row=2, column=0, columnspan=3, sticky='w', pady=(10, 6))
        self.mask_combo = self.ttk.Combobox(controls, textvariable=self.mask_profile_var,
            values=tuple(MASK_LABELS), state='readonly')
        self.mask_combo.grid(row=3, column=0, columnspan=2, sticky='ew', padx=(0, 10))
        self.mask_combo.bind('<<ComboboxSelected>>', lambda _event: self._refresh_mask_status())
        self.edit_mask_button = self.ttk.Button(controls, text='Draw / edit custom…', command=self.edit_mask)
        self.edit_mask_button.grid(row=3, column=2, sticky='ew')
        controls.rowconfigure(4, minsize=48)
        self.ttk.Label(controls, textvariable=self.mask_summary_var, style='Muted.TLabel',
                       wraplength=730, justify='left').grid(row=4, column=0, columnspan=3, sticky='ew', pady=(7, 0))

        body = self.ttk.Frame(outer, style="App.TFrame")
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="body")
        body.columnconfigure(1, weight=1, uniform="body")
        body.rowconfigure(0, weight=1)

        advanced = self.ttk.Frame(body, style="Panel.TFrame", padding=12)
        advanced.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        advanced.columnconfigure(0, weight=1)
        self.ttk.Label(advanced, text="Advanced processing", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 9))
        self.ttk.Label(advanced, text="NR input height", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.nr_height_frame = self._radio_row(advanced, 2, self.nr_height_var, (720, 900, 1080))
        self.ttk.Label(advanced, text="Optical flow width", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.flow_width_frame = self._radio_row(advanced, 4, self.flow_width_var, (320, 640, 960, 1280))
        self.ttk.Label(advanced, text="Flow grid", style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.flow_grid_frame = self._radio_row(advanced, 6, self.flow_grid_var, (2, 4), prefix="G")
        self.ttk.Label(advanced, text="Flow preset", style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.flow_preset_frame = self._radio_row(advanced, 8, self.flow_preset_var, ("fast", "medium", "slow"), title_case=True)

        preference_actions = self.ttk.Frame(advanced, style="Panel.TFrame")
        preference_actions.grid(row=9, column=0, sticky="ew", pady=(13, 0))
        preference_actions.columnconfigure(0, weight=1)
        preference_actions.columnconfigure(1, weight=1)
        self.save_button = self.ttk.Button(preference_actions, text="Save preferences", command=self.save_preferences)
        self.save_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.restore_button = self.ttk.Button(preference_actions, text="Restore recommended", command=self.restore_recommended)
        self.restore_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        status = self.ttk.Frame(body, style="Panel.TFrame", padding=12)
        status.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        status.columnconfigure(0, weight=1)
        status.rowconfigure(2, minsize=76)
        status.rowconfigure(4, minsize=64)
        self.ttk.Label(status, text="System status", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.status_state_label = self.ttk.Label(status, textvariable=self.status_state_var, style="State.TLabel")
        self.status_state_label.grid(row=1, column=0, sticky="w", pady=(4, 2))
        self.status_detail_label = self.ttk.Label(
            status,
            textvariable=self.status_detail_var,
            style="Muted.TLabel",
            wraplength=310,
            justify="left",
        )
        self.status_detail_label.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.ttk.Label(status, text="Processing / output geometry", style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        self.ttk.Label(status, textvariable=self.geometry_var, style="Value.TLabel", wraplength=300).grid(row=4, column=0, sticky="ew", pady=(3, 8))
        self.ttk.Label(status, text="Neural Rendering (NR)", style="Muted.TLabel").grid(row=5, column=0, sticky="w")
        self.ttk.Label(status, textvariable=self.nr_status_var, style="Value.TLabel").grid(row=6, column=0, sticky="ew", pady=(3, 8))
        self.ttk.Label(status, text="Hardware optical flow", style="Muted.TLabel").grid(row=7, column=0, sticky="w")
        self.ttk.Label(status, textvariable=self.flow_status_var, style="Value.TLabel").grid(row=8, column=0, sticky="ew", pady=(3, 10))
        self.open_run_button = self.ttk.Button(status, text="Open run folder", command=self.open_run_folder)
        self.open_run_button.grid(row=9, column=0, sticky="ew")

        self.ttk.Label(
            outer,
            text=(
                "HUD Mask is off by default. Draw fixed screen regions per game and resolution; recapture after layout changes. SDR only. "
                "Stop before changing settings. Ctrl+Alt+Q: stop · Ctrl+Alt+F9: panel · Ctrl+Alt+F8: toggle NR."
            ),
            style="Subtitle.TLabel",
            wraplength=740,
            justify="left",
        ).grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _radio_row(
        self,
        parent: Any,
        row: int,
        variable: Any,
        values: tuple[Any, ...],
        *,
        prefix: str = "",
        title_case: bool = False,
    ) -> Any:
        frame = self.ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(2, 0))
        for column, value in enumerate(values):
            frame.columnconfigure(column, weight=1)
            label = str(value).title() if title_case else f"{prefix}{value}"
            button = self.ttk.Radiobutton(frame, text=label, variable=variable, value=value)
            button.grid(row=0, column=column, sticky="w", padx=(0, 7))
        return frame

    def _load_settings(self) -> None:
        saved = dict(RECOMMENDED_SETTINGS)
        try:
            saved.update(self.controller.settings or {})
        except Exception:
            _write_error_log("Failed to read saved UI settings")
        self._apply_settings_to_form(saved)

    def _apply_settings_to_form(self, settings: dict[str, Any]) -> None:
        mode = settings.get("mode", "nr")
        self.mask_enabled_var.set(mode == 'guard')
        if mode == 'guard':
            mode = 'nr'
        if mode not in MODE_VALUES_TO_LABELS:
            mode = "nr"
        self.mode_var.set(MODE_VALUES_TO_LABELS[mode])
        self.mask_profile_var.set(next(label for label, value in MASK_LABELS.items()
                                      if value == settings.get('mask_profile', 'custom')))
        self.nr_height_var.set(settings.get("nr_height", 720))
        self.flow_width_var.set(settings.get("flow_width", 1280))
        self.flow_grid_var.set(settings.get("flow_grid", 2))
        self.flow_preset_var.set(settings.get("flow_preset", "fast"))

    def _settings_from_form(self) -> dict[str, Any]:
        return {
            "nr_height": int(self.nr_height_var.get()),
            "flow_width": int(self.flow_width_var.get()),
            "flow_grid": int(self.flow_grid_var.get()),
            "flow_preset": self.flow_preset_var.get(),
            "mode": ('bypass' if MODE_LABELS.get(self.mode_var.get()) == 'bypass' else
                     ('guard' if self.mask_enabled_var.get() else 'nr')),
            "mask_profile": MASK_LABELS[self.mask_profile_var.get()],
        }

    def edit_mask(self) -> None:
        target = self.target_by_display.get(self.target_var.get())
        if not target or self._controller_busy():
            return
        try:
            from mask_editor import open_editor
            def saved():
                profile = self.controller.load_mask_profile(target)
                self.mask_profile_var.set(next(label for label, value in MASK_LABELS.items() if value == 'custom'))
                self.mask_enabled_var.set(bool(profile and profile['rectangles']))
                self.controller.save_settings(self._settings_from_form())
                self._refresh_mask_status()
            open_editor(self.root, self.controller, target, saved)
        except Exception as exc:
            _write_error_log('Mask editor failed')
            self.messagebox.showerror(APP_TITLE, f'Could not open the mask editor.\n\n{exc}')
            self.root.deiconify()

    def refresh_targets(self) -> None:
        previous_hwnd = None
        selected = self.target_by_display.get(self.target_var.get())
        if selected:
            previous_hwnd = selected.get("hwnd")
        try:
            self.targets = list(self.controller.list_targets())
        except Exception as exc:
            _write_error_log("Failed to enumerate target windows")
            self.messagebox.showerror(APP_TITLE, f"Could not refresh game windows.\n\n{exc}")
            self.targets = []

        self.target_by_display.clear()
        labels: list[str] = []
        selected_label = ""
        for target in self.targets:
            title = str(target.get("title") or "Untitled window").strip()
            width = target.get("width", "?")
            height = target.get("height", "?")
            pid = target.get("pid", "?")
            hwnd = target.get("hwnd", "?")
            label = f"{title}  ·  {width}×{height}  ·  PID {pid}"
            if label in self.target_by_display:
                label = f"{label}  ·  HWND {hwnd}"
            self.target_by_display[label] = target
            labels.append(label)
            if previous_hwnd is not None and hwnd == previous_hwnd:
                selected_label = label

        self.target_combo.configure(values=labels)
        if not labels:
            self.target_var.set("")
            if not self.controller.busy:
                self.status_detail_var.set("No eligible game window found. Open the GeForce NOW game, then refresh.")
        elif selected_label:
            self.target_var.set(selected_label)
        else:
            self.target_var.set(labels[0])
        self._refresh_mask_status()

    def save_preferences(self) -> None:
        try:
            self.controller.save_settings(self._settings_from_form())
            self.status_detail_var.set("Preferences saved for future launches.")
            self._refresh_mask_status()
        except Exception as exc:
            _write_error_log("Failed to save UI settings")
            self.messagebox.showerror(APP_TITLE, f"Could not save preferences.\n\n{exc}")

    def restore_recommended(self) -> None:
        self._apply_settings_to_form(RECOMMENDED_SETTINGS)
        try:
            self.controller.save_settings(dict(RECOMMENDED_SETTINGS))
            self.status_detail_var.set("Recommended NR720, flow 1280, G2 Fast, mask off restored and saved.")
            self._refresh_mask_status()
        except Exception as exc:
            _write_error_log("Failed to restore recommended settings")
            self.messagebox.showerror(APP_TITLE, f"Recommended values were restored on screen but could not be saved.\n\n{exc}")

    def start(self) -> None:
        target = self.target_by_display.get(self.target_var.get())
        if not target:
            self.messagebox.showwarning(APP_TITLE, "Choose an eligible GeForce NOW game window first.")
            return
        try:
            settings = self._settings_from_form()
            self.controller.start(target, settings)
            self._last_state = "starting"
            self.status_state_var.set("STARTING")
            self.status_detail_var.set("Starting the isolated native pipeline…")
            self._sync_controls()
        except Exception as exc:
            _write_error_log("Failed to start the daily pipeline")
            self.messagebox.showerror(APP_TITLE, f"The pipeline could not start.\n\n{exc}")
            self._sync_controls()

    def stop(self) -> None:
        try:
            self.controller.stop()
            self._last_state = "stopping"
            self.status_state_var.set("STOPPING")
            self.status_detail_var.set("Requesting a safe stop…")
            self._sync_controls()
        except Exception as exc:
            _write_error_log("Failed to request a safe stop")
            self.messagebox.showerror(APP_TITLE, f"Could not request a safe stop.\n\n{exc}")

    def _poll_controller(self) -> None:
        try:
            snapshot = self.controller.poll()
            self._set_status(
                state=str(snapshot.get("state", "error")),
                detail=str(snapshot.get("detail") or "No status detail was provided."),
                geometry=str(snapshot.get("geometry") or "Not reported"),
                nr_confirmed=bool(snapshot.get("nr_confirmed", False)),
                hardware_flow_active=bool(snapshot.get("hardware_flow_active", False)),
                run=snapshot.get("run"),
            )
        except Exception as exc:
            _write_error_log("Failed while polling the daily pipeline")
            self._last_state = "error"
            self.status_state_var.set("ERROR")
            self.status_detail_var.set(f"Status polling failed: {exc}")
            if self._closing and self._controller_busy():
                self._closing = False
                self._stop_requested_for_close = False
                self.status_detail_var.set(f"Safe shutdown could not be verified; the panel remains open. {exc}")
            self._sync_controls()

        if (
            self._closing
            and self._last_state in {"idle", "stopped", "error"}
            and not self._controller_busy()
        ):
            self.root.destroy()
            return
        self.root.after(POLL_INTERVAL_MS, self._poll_controller)

    def _controller_busy(self) -> bool:
        try:
            return bool(self.controller.busy)
        except Exception:
            return self._last_state in {"starting", "running", "suspended", "stopping"}

    def _set_status(
        self,
        *,
        state: str,
        detail: str,
        geometry: str,
        nr_confirmed: bool,
        hardware_flow_active: bool,
        run: Any,
    ) -> None:
        normalized = state if state in {"idle", "starting", "running", "suspended", "stopping", "stopped", "error"} else "error"
        if normalized == 'idle' and not self.targets:
            detail = 'No eligible GFN game found. Open a game, then click Refresh.'
        self._last_state = normalized
        self.status_state_var.set(normalized.upper())
        self.status_detail_var.set(detail)
        self.geometry_var.set(geometry)
        inactive = {"idle": "Ready to start", "starting": "Initializing", "suspended": "Paused",
                    "stopping": "Stopping", "stopped": "Stopped", "error": "Unavailable"}.get(normalized, "Inactive / bypass")
        self.nr_status_var.set("Confirmed active" if nr_confirmed else inactive)
        self.flow_status_var.set("Active" if hardware_flow_active else inactive)

        self._run_path = None
        if run:
            candidate = Path(str(run))
            if candidate.is_absolute():
                self._run_path = candidate
        self._sync_controls()

    def _refresh_mask_status(self) -> None:
        target = self.target_by_display.get(self.target_var.get())
        try:
            status = self.controller.mask_status(target, self._settings_from_form())
            self._mask_ready = bool(status['usable'])
            self.mask_summary_var.set(status['detail'])
        except Exception as exc:
            self._mask_ready = False
            self.mask_summary_var.set('Could not verify the mask configuration: '+str(exc))
        self._sync_controls()

    def _sync_controls(self) -> None:
        busy = self._controller_busy()

        settings_state = "disabled" if busy or self._closing else "readonly"
        self.target_combo.configure(state=settings_state)
        self.mode_combo.configure(state=settings_state)
        self.refresh_button.configure(state="disabled" if busy or self._closing else "normal")
        self.save_button.configure(state="disabled" if busy or self._closing else "normal")
        self.restore_button.configure(state="disabled" if busy or self._closing else "normal")
        editable = not busy and not self._closing and MODE_LABELS.get(self.mode_var.get()) != 'bypass'
        self.mask_check.configure(state='normal' if editable else 'disabled')
        self.mask_combo.configure(state='readonly' if editable else 'disabled')
        self.edit_mask_button.configure(state='normal' if editable and self.target_var.get() in self.target_by_display else 'disabled')

        for frame in (self.nr_height_frame, self.flow_width_frame, self.flow_grid_frame, self.flow_preset_frame):
            for child in frame.winfo_children():
                child.configure(state="disabled" if busy or self._closing else "normal")

        has_target = self.target_var.get() in self.target_by_display
        self.start_button.configure(state="normal" if has_target and self._mask_ready and not busy and not self._closing else "disabled")
        self.stop_button.configure(state="normal" if busy and self._last_state != "stopping" and not self._closing else "disabled")
        self.open_run_button.configure(
            state="normal" if self._run_path is not None and self._run_path.is_dir() else "disabled"
        )

    def open_run_folder(self) -> None:
        path = self._run_path
        if path is None or not path.is_absolute() or not path.is_dir():
            self.messagebox.showwarning(APP_TITLE, "The run folder is not available yet.")
            return
        if sys.platform != "win32":
            self.messagebox.showerror(APP_TITLE, "Run folders can only be opened by this launcher on Windows.")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            _write_error_log("Failed to open an explicit run folder")
            self.messagebox.showerror(APP_TITLE, f"Could not open the run folder.\n\n{exc}")

    def on_close(self) -> None:
        if self._closing:
            return
        busy = self._controller_busy()
        if not busy:
            self.root.destroy()
            return

        should_close = self.messagebox.askyesno(
            APP_TITLE,
            "The pipeline is still active. Stop it safely and close after shutdown completes?",
            icon="warning",
        )
        if not should_close:
            return

        self._closing = True
        self.status_detail_var.set("Waiting for the pipeline to stop before closing…")
        self._sync_controls()
        if not self._stop_requested_for_close:
            self._stop_requested_for_close = True
            try:
                self.controller.stop()
            except Exception as exc:
                _write_error_log("Failed to stop the pipeline while closing")
                self._closing = False
                self._stop_requested_for_close = False
                self._sync_controls()
                self.messagebox.showerror(APP_TITLE, f"The pipeline could not be stopped, so the window will remain open.\n\n{exc}")


def main() -> int:
    """Launch the daily UI. Returns zero when a duplicate instance is focused."""
    instance: SingleInstanceGuard | None = None
    root: Any = None
    try:
        instance = SingleInstanceGuard()
        if instance.already_running:
            return 0

        _enable_windows_dpi_awareness()
        import tkinter as tk

        from daily_backend import DailyController

        root = tk.Tk()
        controller = DailyController(root=APP_DIR)
        DailyApp(root, controller)
        root.mainloop()
        return 0
    except Exception:
        _write_error_log("Geforce NR daily UI startup failure")
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        _show_startup_error(
            "Geforce NR could not start.\n\n"
            f"A diagnostic traceback was written to:\n{ERROR_LOG}"
        )
        return 1
    finally:
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
