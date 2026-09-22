"""Native tkinter rectangle editor for HUD mask profiles.

The editor intentionally uses only the Python standard library so it can run in
the existing Windows Core environment.  Capture and persistence remain owned by
the controller supplied by ``daily_ui``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence


# Tk is loaded only when the editor opens.  This keeps coordinate-only tests
# importable in tooling environments whose Python build does not include Tk.
tk: Any = None
ttk: Any = None
messagebox: Any = None


def _load_tk() -> None:
    global tk, ttk, messagebox
    if tk is not None:
        return
    import tkinter as tkinter_module
    from tkinter import messagebox as messagebox_module
    from tkinter import ttk as ttk_module

    tk = tkinter_module
    ttk = ttk_module
    messagebox = messagebox_module


MAX_REGIONS = 64
MIN_REGION_SIZE = 2
CAPTURE_DELAY_MS = 180
MAX_PREVIEW_WIDTH = 1000
MAX_PREVIEW_HEIGHT = 650


def validate_rectangle_fields(
    values: Sequence[str],
    *,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    """Validate four text fields as a bounded, half-open image rectangle."""
    if len(values) != 4:
        raise ValueError("Enter exactly four coordinates: x0, y0, x1, and y1.")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (image_width, image_height)
    ):
        raise ValueError("Image dimensions must be positive integers.")

    coordinates: list[int] = []
    for label, raw_value in zip(("x0", "y0", "x1", "y1"), values):
        if not isinstance(raw_value, str):
            raise ValueError(f"{label} must be an integer.")
        value = raw_value.strip()
        digits = value[1:] if value and value[0] in "+-" else value
        if not digits or not digits.isascii() or not digits.isdigit():
            raise ValueError(f"{label} must be an integer.")
        coordinates.append(int(value, 10))

    left, top, right, bottom = coordinates
    if not (0 <= left < right <= image_width and 0 <= top < bottom <= image_height):
        raise ValueError(
            f"Coordinates must satisfy 0 ≤ x0 < x1 ≤ {image_width} and "
            f"0 ≤ y0 < y1 ≤ {image_height}."
        )
    if right - left < MIN_REGION_SIZE or bottom - top < MIN_REGION_SIZE:
        raise ValueError("Regions must be at least 2 × 2 source pixels.")
    return left, top, right, bottom


def canvas_rect_to_image(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    image_width: int,
    image_height: int,
    display_width: int,
    display_height: int,
    subsample_factor: int,
) -> tuple[int, int, int, int]:
    """Map a canvas rectangle to a clamped half-open image rectangle.

    The canvas contains only the image and has no padding.  Lower bounds are
    rounded down and upper bounds up so every touched source pixel is included.
    Tk's ``subsample(n, n)`` selects source pixels on exact multiples of ``n``.
    The final displayed row or column can cover less than a full scale unit, so
    the factor (rather than a source/display ratio) defines interior mapping.
    """
    dimensions = (image_width, image_height, display_width, display_height)
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in dimensions):
        raise ValueError("Image and display dimensions must be positive integers.")
    if isinstance(subsample_factor, bool) or not isinstance(subsample_factor, int) or subsample_factor <= 0:
        raise ValueError("The subsample factor must be a positive integer.")
    if (
        math.ceil(image_width / subsample_factor) != display_width
        or math.ceil(image_height / subsample_factor) != display_height
    ):
        raise ValueError("Display dimensions do not match the Tk subsample factor.")

    left = min(max(min(float(x0), float(x1)), 0.0), float(display_width))
    right = min(max(max(float(x0), float(x1)), 0.0), float(display_width))
    top = min(max(min(float(y0), float(y1)), 0.0), float(display_height))
    bottom = min(max(max(float(y0), float(y1)), 0.0), float(display_height))

    image_left = max(0, min(image_width, math.floor(left * subsample_factor)))
    image_right = max(0, min(image_width, math.ceil(right * subsample_factor)))
    image_top = max(0, min(image_height, math.floor(top * subsample_factor)))
    image_bottom = max(0, min(image_height, math.ceil(bottom * subsample_factor)))
    return image_left, image_top, image_right, image_bottom


def _ppm_dimensions_and_payload(ppm: bytes) -> tuple[int, int, int]:
    """Return P6 width, height, and payload offset after strict validation."""
    if not isinstance(ppm, bytes):
        raise ValueError("Capture data must be P6 PPM bytes.")

    position = 0
    tokens: list[bytes] = []
    length = len(ppm)
    while len(tokens) < 4:
        while position < length:
            byte = ppm[position]
            if byte in b" \t\r\n":
                position += 1
                continue
            if byte == ord("#"):
                newline = ppm.find(b"\n", position + 1)
                if newline < 0:
                    raise ValueError("Capture returned an incomplete PPM header.")
                position = newline + 1
                continue
            break
        start = position
        while position < length and ppm[position] not in b" \t\r\n#":
            position += 1
        if start == position:
            raise ValueError("Capture returned an incomplete PPM header.")
        tokens.append(ppm[start:position])

    if tokens[0] != b"P6":
        raise ValueError("Capture data is not a binary P6 PPM image.")
    try:
        width, height, maximum = (int(token) for token in tokens[1:])
    except ValueError as error:
        raise ValueError("Capture returned an invalid PPM header.") from error
    if width <= 0 or height <= 0 or maximum != 255:
        raise ValueError("Capture returned unsupported PPM dimensions or color depth.")
    if position >= length or ppm[position] not in b" \t\r\n":
        raise ValueError("Capture returned an incomplete PPM header.")
    payload_offset = position + 1
    if ppm[position] == ord("\r") and payload_offset < length and ppm[payload_offset] == ord("\n"):
        payload_offset += 1
    if len(ppm) - payload_offset != width * height * 3:
        raise ValueError("Capture returned an incomplete RGB image.")
    return width, height, payload_offset


class MaskEditor:
    """Modal rectangle mask editor backed by a controller contract."""

    def __init__(
        self,
        parent: Any,
        controller: Any,
        target_dict: dict[str, Any],
        on_saved: Callable[[], None] | None,
    ) -> None:
        _load_tk()
        self.parent = parent
        self.controller = controller
        self.target_dict = target_dict
        self.on_saved = on_saved
        self._parent_state = self._safe_parent_state()
        self._parent_restored = False
        self._closed = False
        self._capture_complete = False
        self._image_width = 0
        self._image_height = 0
        self._display_width = 0
        self._display_height = 0
        self._subsample_factor = 1
        self._drag_start: tuple[float, float] | None = None
        self._drag_item: int | None = None
        self._undo_states: list[list[tuple[int, int, int, int]]] = []
        self.rectangles: list[tuple[int, int, int, int]] = []
        self._baseline_rectangles: list[tuple[int, int, int, int]] = []
        self._coordinate_index: int | None = None
        self._selection_syncing = False
        self.coordinate_vars: list[Any] = []

        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("HUD Mask Editor")
        self.window.configure(background="#111a1d")
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.resizable(False, False)
        try:
            self.window.transient(parent)
        except tk.TclError:
            pass
        # Public widget handles used by the UI probe and integration checks.
        self.canvas: tk.Canvas | None = None
        self.delete_button: ttk.Button | None = None
        self.clear_button: ttk.Button | None = None
        self.save_button: ttk.Button | None = None

        self._hide_parent()
        self.window.after(CAPTURE_DELAY_MS, self._capture_and_build)

    def _safe_parent_state(self) -> str:
        try:
            return str(self.parent.state())
        except (AttributeError, tk.TclError):
            return "normal"

    def _hide_parent(self) -> None:
        try:
            self.parent.withdraw()
        except (AttributeError, tk.TclError):
            pass

    def _restore_parent(self) -> None:
        if self._parent_restored:
            return
        self._parent_restored = True
        try:
            if self._parent_state == "withdrawn":
                self.parent.withdraw()
                return
            self.parent.deiconify()
            if self._parent_state in {"iconic", "zoomed", "normal"}:
                self.parent.state(self._parent_state)
            self.parent.update_idletasks()
        except (AttributeError, tk.TclError):
            pass

    def _capture_and_build(self) -> None:
        if self._closed:
            self._restore_parent()
            return
        try:
            capture = self.controller.capture_target(self.target_dict)
            width, height, ppm = self._validate_capture(capture)
            source_image = tk.PhotoImage(master=self.window, data=ppm, format="PPM")
            factor = max(
                1,
                math.ceil(max(width / MAX_PREVIEW_WIDTH, height / MAX_PREVIEW_HEIGHT)),
            )
            display_image = source_image if factor == 1 else source_image.subsample(factor, factor)
            self._source_image = source_image
            self._display_image = display_image
            self._image_width = width
            self._image_height = height
            self._display_width = display_image.width()
            self._display_height = display_image.height()
            self._subsample_factor = factor
            self._capture_complete = True
            profile_notice = self._load_profile()
            self._baseline_rectangles = list(self.rectangles)
            self._build_ui(profile_notice)
        except Exception as error:
            self._restore_parent()
            self._closed = True
            try:
                self.window.grab_release()
            except tk.TclError:
                pass
            self.window.destroy()
            messagebox.showerror(
                "HUD Mask Editor",
                f"Could not open the mask editor.\n\n{error}",
                parent=self.parent,
            )
            return

        self._restore_parent()
        self.window.deiconify()
        self.window.update_idletasks()
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()

    @staticmethod
    def _validate_capture(capture: Any) -> tuple[int, int, bytes]:
        if not isinstance(capture, dict):
            raise ValueError("Capture returned an invalid result.")
        width = capture.get("width")
        height = capture.get("height")
        ppm = capture.get("ppm")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError("Capture returned an invalid width.")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ValueError("Capture returned an invalid height.")
        if isinstance(ppm, bytearray):
            ppm = bytes(ppm)
        ppm_width, ppm_height, _payload = _ppm_dimensions_and_payload(ppm)
        if (ppm_width, ppm_height) != (width, height):
            raise ValueError("Capture dimensions do not match the PPM image.")
        return width, height, ppm

    def _load_profile(self) -> str:
        try:
            profile = self.controller.load_mask_profile(self.target_dict)
        except Exception as error:
            raise ValueError(f"The saved mask could not be loaded: {error}") from error
        if profile is None:
            return "Draw rectangles over HUD areas that should remain unprocessed."
        if not isinstance(profile, dict):
            raise ValueError("The saved mask has an invalid format.")
        if (profile.get("width"), profile.get("height")) != (
            self._image_width,
            self._image_height,
        ):
            raise ValueError("The saved mask belongs to different capture dimensions.")
        raw_rectangles = profile.get("rectangles")
        if not isinstance(raw_rectangles, list) or len(raw_rectangles) > MAX_REGIONS:
            raise ValueError("The saved mask has an invalid region list.")
        loaded: list[tuple[int, int, int, int]] = []
        for raw in raw_rectangles:
            if not isinstance(raw, (list, tuple)) or len(raw) != 4:
                raise ValueError("The saved mask contains an invalid region.")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in raw):
                raise ValueError("The saved mask contains non-integer coordinates.")
            left, top, right, bottom = raw
            if not (
                0 <= left < right <= self._image_width
                and 0 <= top < bottom <= self._image_height
                and right - left >= MIN_REGION_SIZE
                and bottom - top >= MIN_REGION_SIZE
            ):
                raise ValueError("The saved mask contains an out-of-bounds region.")
            loaded.append((left, top, right, bottom))
        self.rectangles = loaded
        if loaded:
            return f"Loaded {len(loaded)} saved region{'s' if len(loaded) != 1 else ''}."
        return "The saved mask is empty. Saving it disables mask use."

    def _configure_style(self) -> None:
        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Mask.App.TFrame", background="#111a1d")
        style.configure("Mask.Panel.TFrame", background="#192529")
        style.configure(
            "Mask.Header.TLabel",
            background="#111a1d",
            foreground="#edf4f2",
            font=("Segoe UI Semibold", 18),
        )
        style.configure(
            "Mask.Body.TLabel",
            background="#192529",
            foreground="#edf4f2",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Mask.Muted.TLabel",
            background="#192529",
            foreground="#aebdb9",
            font=("Segoe UI", 9),
            wraplength=235,
        )
        style.configure("Mask.TButton", font=("Segoe UI Semibold", 9), padding=(10, 7))
        style.configure(
            "Mask.Primary.TButton",
            background="#4fd18b",
            foreground="#0a2116",
            bordercolor="#4fd18b",
            font=("Segoe UI Semibold", 10),
            padding=(12, 8),
        )
        style.map(
            "Mask.Primary.TButton",
            background=[("active", "#69dea0"), ("disabled", "#425851")],
            foreground=[("disabled", "#96a29f")],
        )

    def _build_ui(self, notice: str) -> None:
        self._configure_style()
        outer = ttk.Frame(self.window, style="Mask.App.TFrame", padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        ttk.Label(outer, text="HUD Mask Editor", style="Mask.Header.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        canvas_border = tk.Frame(outer, background="#385057", padx=1, pady=1)
        canvas_border.grid(row=1, column=0, sticky="nw")
        self.canvas = tk.Canvas(
            canvas_border,
            width=self._display_width,
            height=self._display_height,
            background="#080d0f",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self._display_image)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        sidebar = ttk.Frame(outer, style="Mask.Panel.TFrame", padding=12, width=260)
        sidebar.grid(row=1, column=1, sticky="ns", padx=(12, 0))
        ttk.Label(sidebar, text="Protected regions", style="Mask.Body.TLabel").pack(anchor="w")
        self.region_list = tk.Listbox(
            sidebar,
            height=10,
            background="#213137",
            foreground="#edf4f2",
            selectbackground="#4b6b64",
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#385057",
            highlightcolor="#4fd18b",
            activestyle="none",
            exportselection=False,
            font=("Consolas", 9),
        )
        self.region_list.pack(fill="x", pady=(8, 8))
        self.region_list.bind("<<ListboxSelect>>", self._on_list_selection)

        action_row = ttk.Frame(sidebar, style="Mask.Panel.TFrame")
        action_row.pack(fill="x")
        self.delete_button = ttk.Button(
            action_row, text="Delete selected", style="Mask.TButton", command=self._delete_selected
        )
        self.delete_button.pack(side="left", fill="x", expand=True)
        self.undo_button = ttk.Button(
            action_row, text="Undo last", style="Mask.TButton", command=self._undo
        )
        self.undo_button.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.clear_button = ttk.Button(
            sidebar, text="Clear all", style="Mask.TButton", command=self._clear_all
        )
        self.clear_button.pack(fill="x", pady=(6, 0))

        coordinates = ttk.Frame(sidebar, style="Mask.Panel.TFrame")
        coordinates.pack(fill="x", pady=(12, 0))
        ttk.Label(coordinates, text="Selected region (source pixels)", style="Mask.Body.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        self.coordinate_vars = [tk.StringVar() for _label in range(4)]
        self.coordinate_entries = []
        for column, (label, variable) in enumerate(
            zip(("x0", "y0", "x1", "y1"), self.coordinate_vars)
        ):
            ttk.Label(coordinates, text=label, style="Mask.Muted.TLabel").grid(
                row=1, column=column, sticky="w"
            )
            entry = ttk.Entry(coordinates, textvariable=variable, width=7, state="disabled")
            entry.grid(row=2, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))
            self.coordinate_entries.append(entry)
            coordinates.columnconfigure(column, weight=1)
        self.apply_button = ttk.Button(
            coordinates,
            text="Apply selected",
            style="Mask.TButton",
            command=self._apply_selected_coordinates,
            state="disabled",
        )
        self.apply_button.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        self.notice_var = tk.StringVar(value=notice)
        self.notice_label = ttk.Label(
            sidebar,
            textvariable=self.notice_var,
            style="Mask.Muted.TLabel",
            justify="left",
        )
        self.notice_label.pack(fill="x", pady=(12, 8))
        ttk.Label(
            sidebar,
            text="Saving an empty list clears the profile and disables mask use.",
            style="Mask.Muted.TLabel",
            justify="left",
        ).pack(fill="x")

        footer = ttk.Frame(sidebar, style="Mask.Panel.TFrame")
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(footer, text="Cancel", style="Mask.TButton", command=self.cancel).pack(
            side="left", fill="x", expand=True
        )
        self.save_button = ttk.Button(
            footer,
            text="Save & use",
            style="Mask.Primary.TButton",
            command=self._save,
        )
        self.save_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.window.bind("<Escape>", lambda _event: self.cancel())
        self.window.bind("<Delete>", self._on_delete_key)
        self.window.bind("<Control-z>", self._on_undo_key)
        self.window.bind("<Control-s>", lambda _event: self._save() or "break")
        self._refresh_regions()
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _image_rect_to_canvas(self, rectangle: Sequence[int]) -> tuple[float, float, float, float]:
        left, top, right, bottom = rectangle
        return (
            self._image_boundary_to_canvas(left, self._image_width, self._display_width),
            self._image_boundary_to_canvas(top, self._image_height, self._display_height),
            self._image_boundary_to_canvas(right, self._image_width, self._display_width),
            self._image_boundary_to_canvas(bottom, self._image_height, self._display_height),
        )

    def _image_boundary_to_canvas(self, value: int, image_size: int, display_size: int) -> float:
        if value >= image_size:
            return float(display_size)
        return min(max(value / self._subsample_factor, 0.0), float(display_size))

    def _refresh_regions(self, selected: int | None = None) -> None:
        if self.canvas is None:
            return
        if selected is None:
            selection = self.region_list.curselection()
            selected = selection[0] if selection else None
        self.region_list.delete(0, tk.END)
        self.canvas.delete("mask-region")
        for index, rectangle in enumerate(self.rectangles):
            left, top, right, bottom = rectangle
            self.region_list.insert(
                tk.END,
                f"{index + 1:02d}  ({left}, {top}) – ({right}, {bottom})",
            )
            color = "#ffd166" if index == selected else "#4fd18b"
            self.canvas.create_rectangle(
                *self._image_rect_to_canvas(rectangle),
                outline=color,
                width=2,
                tags=("mask-region", f"mask-region-{index}"),
            )
        if selected is not None and 0 <= selected < len(self.rectangles):
            self.region_list.selection_set(selected)
            self.region_list.activate(selected)
            self.region_list.see(selected)
        self.delete_button.configure(state="normal" if self.region_list.curselection() else "disabled")
        self.clear_button.configure(state="normal" if self.rectangles else "disabled")
        self.undo_button.configure(state="normal" if self._undo_states else "disabled")
        self._show_selected_coordinates(selected)

    def _on_list_selection(self, _event: Any = None) -> None:
        if self._selection_syncing:
            return
        selection = self.region_list.curselection()
        selected = selection[0] if selection else None
        previous = self._coordinate_index
        if selected == previous and self._coordinates_are_pending():
            self._paint_selection(selected)
            return
        if selected != previous and self._coordinates_are_pending():
            self._selection_syncing = True
            try:
                if not self._apply_selected_coordinates():
                    self.region_list.selection_clear(0, tk.END)
                    if previous is not None and 0 <= previous < len(self.rectangles):
                        self.region_list.selection_set(previous)
                        self.region_list.activate(previous)
                        self.region_list.see(previous)
                    self._paint_selection(previous)
                    self.delete_button.configure(state="normal" if previous is not None else "disabled")
                    return
                self.region_list.selection_clear(0, tk.END)
                if selected is not None and 0 <= selected < len(self.rectangles):
                    self.region_list.selection_set(selected)
                    self.region_list.activate(selected)
                    self.region_list.see(selected)
            finally:
                self._selection_syncing = False
        self._paint_selection(selected)
        self.delete_button.configure(state="normal" if selected is not None else "disabled")
        self._show_selected_coordinates(selected)

    def _paint_selection(self, selected: int | None) -> None:
        for index in range(len(self.rectangles)):
            self.canvas.itemconfigure(
                f"mask-region-{index}",
                outline="#ffd166" if index == selected else "#4fd18b",
            )

    def _show_selected_coordinates(self, selected: int | None) -> None:
        self._coordinate_index = (
            selected if selected is not None and 0 <= selected < len(self.rectangles) else None
        )
        if not self.coordinate_vars:
            return
        values = (
            self.rectangles[self._coordinate_index]
            if self._coordinate_index is not None
            else ("",) * 4
        )
        for variable, value in zip(self.coordinate_vars, values):
            variable.set(str(value))
        state = "normal" if self._coordinate_index is not None else "disabled"
        for entry in self.coordinate_entries:
            entry.configure(state=state)
        self.apply_button.configure(state=state)

    def _coordinate_texts(self) -> tuple[str, str, str, str]:
        return tuple(variable.get() for variable in self.coordinate_vars)  # type: ignore[return-value]

    def _coordinates_are_pending(self) -> bool:
        index = self._coordinate_index
        if (
            index is None
            or not (0 <= index < len(self.rectangles))
            or len(self.coordinate_vars) != 4
        ):
            return False
        expected = tuple(str(value) for value in self.rectangles[index])
        return self._coordinate_texts() != expected

    def _has_unsaved_changes(self) -> bool:
        return self.rectangles != self._baseline_rectangles or self._coordinates_are_pending()

    def _apply_selected_coordinates(self) -> bool:
        index = self._coordinate_index
        if index is None or not (0 <= index < len(self.rectangles)):
            self.notice_var.set("Select a region before editing its coordinates.")
            return False
        try:
            rectangle = validate_rectangle_fields(
                self._coordinate_texts(),
                image_width=self._image_width,
                image_height=self._image_height,
            )
        except ValueError as error:
            self.notice_var.set(str(error))
            return False
        if rectangle == self.rectangles[index]:
            self.notice_var.set("Selected region coordinates are unchanged.")
            self._show_selected_coordinates(index)
            return True
        self._record_undo()
        self.rectangles[index] = rectangle
        self.notice_var.set("Selected region coordinates updated.")
        self._refresh_regions(index)
        return True

    def _focus_is_text_input(self) -> bool:
        try:
            focused = self.window.focus_get()
            return focused is not None and focused.winfo_class() in {
                "Entry", "TEntry", "Text", "Spinbox", "TSpinbox"
            }
        except (AttributeError, tk.TclError):
            return False

    def _on_delete_key(self, _event: Any = None) -> str | None:
        if self._focus_is_text_input():
            return None
        self._delete_selected()
        return "break"

    def _on_undo_key(self, _event: Any = None) -> str | None:
        if self._focus_is_text_input():
            return None
        self._undo()
        return "break"

    def _clamp_canvas_point(self, x: float, y: float) -> tuple[float, float]:
        return (
            min(max(float(x), 0.0), float(self._display_width)),
            min(max(float(y), 0.0), float(self._display_height)),
        )

    def _on_drag_start(self, event: Any) -> None:
        if len(self.rectangles) >= MAX_REGIONS:
            self.notice_var.set(f"A mask can contain at most {MAX_REGIONS} regions.")
            return
        if self._coordinates_are_pending() and not self._apply_selected_coordinates():
            return
        self.region_list.selection_clear(0, tk.END)
        self._refresh_regions()
        self._drag_start = self._clamp_canvas_point(event.x, event.y)
        self._drag_item = self.canvas.create_rectangle(
            self._drag_start[0],
            self._drag_start[1],
            self._drag_start[0],
            self._drag_start[1],
            outline="#ffd166",
            width=2,
            dash=(5, 3),
            tags=("drag-region",),
        )

    def _on_drag_motion(self, event: Any) -> None:
        if self._drag_start is None or self._drag_item is None:
            return
        x, y = self._clamp_canvas_point(event.x, event.y)
        self.canvas.coords(self._drag_item, self._drag_start[0], self._drag_start[1], x, y)

    def _on_drag_end(self, event: Any) -> None:
        if self._drag_start is None:
            return
        end = self._clamp_canvas_point(event.x, event.y)
        if self._drag_item is not None:
            self.canvas.delete(self._drag_item)
        rectangle = canvas_rect_to_image(
            self._drag_start[0],
            self._drag_start[1],
            end[0],
            end[1],
            image_width=self._image_width,
            image_height=self._image_height,
            display_width=self._display_width,
            display_height=self._display_height,
            subsample_factor=self._subsample_factor,
        )
        self._drag_start = None
        self._drag_item = None
        if rectangle[2] - rectangle[0] < MIN_REGION_SIZE or rectangle[3] - rectangle[1] < MIN_REGION_SIZE:
            self.notice_var.set("Regions must be at least 2 × 2 source pixels.")
            return
        self._record_undo()
        self.rectangles.append(rectangle)
        self.notice_var.set(f"Region {len(self.rectangles)} added.")
        self._refresh_regions(len(self.rectangles) - 1)

    def _record_undo(self) -> None:
        self._undo_states.append(list(self.rectangles))

    def _delete_selected(self) -> None:
        selection = self.region_list.curselection()
        if not selection:
            return
        index = selection[0]
        self._record_undo()
        del self.rectangles[index]
        self.notice_var.set("Selected region deleted.")
        next_selection = min(index, len(self.rectangles) - 1) if self.rectangles else None
        self._refresh_regions(next_selection)

    def _clear_all(self) -> None:
        if not self.rectangles:
            return
        self._record_undo()
        self.rectangles.clear()
        self.notice_var.set("All regions cleared. Save to clear the mask profile.")
        self._refresh_regions()

    def _undo(self) -> None:
        if not self._undo_states:
            return
        self.rectangles = self._undo_states.pop()
        self.notice_var.set("Last edit undone.")
        self._refresh_regions()

    def _save(self) -> None:
        if self._closed or not self._capture_complete:
            return
        if self._coordinates_are_pending() and not self._apply_selected_coordinates():
            return
        try:
            self.controller.save_mask_profile(
                self.target_dict,
                [list(rectangle) for rectangle in self.rectangles],
            )
        except Exception as error:
            messagebox.showerror(
                "HUD Mask Editor",
                f"Could not save the mask profile.\n\n{error}",
                parent=self.window,
            )
            return
        self._finish()
        if self.on_saved is not None:
            try:
                self.on_saved()
            except Exception as error:
                messagebox.showerror(
                    "HUD Mask Editor",
                    f"The mask was saved, but the interface could not refresh.\n\n{error}",
                    parent=self.parent,
                )

    def cancel(self) -> None:
        if self._closed:
            return
        if self._has_unsaved_changes() and not messagebox.askyesno(
            "Discard unsaved changes?",
            "Your region changes have not been saved. Discard them and close the editor?",
            parent=self.window,
            default="no",
        ):
            return
        self._finish()

    def _finish(self) -> None:
        if self._closed:
            self._restore_parent()
            return
        self._closed = True
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        self._restore_parent()
        try:
            self.parent.lift()
            self.parent.focus_force()
        except (AttributeError, tk.TclError):
            pass


def open_editor(
    parent: Any,
    controller: Any,
    target_dict: dict[str, Any],
    on_saved: Callable[[], None] | None = None,
) -> MaskEditor:
    """Open a modal mask editor and return its controller object."""
    return MaskEditor(parent, controller, target_dict, on_saved)


__all__ = ["MaskEditor", "canvas_rect_to_image", "open_editor", "validate_rectangle_fields"]
