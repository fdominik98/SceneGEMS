import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, List, Optional, Sequence


class ModernTable:
    """Reusable, scroll-synced table layout with frozen headers and dividers."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        corner_title: str,
        background: str = "white",
        accent_color: str = "#111827",
        column_separator_color: str = "#d1d5db",
        divider_thickness: int = 4,
        row_header_width: int = 160,
        cell_min_width: int = 150,
        cell_height: int = 1,
    ):
        self.background = background
        self.accent_color = accent_color
        self.column_separator_color = column_separator_color
        self.divider_thickness = divider_thickness
        self.row_header_width = row_header_width
        self.cell_min_width = cell_min_width
        self.cell_height = cell_height
        self.column_count = 0

        base_font = tkfont.Font(family="Segoe UI", size=10)
        line_height = base_font.metrics("linespace")
        self._vertical_padding = 12
        self._horizontal_padding = 12
        self.cell_height_px = max(
            int(line_height * max(self.cell_height, 1) + self._vertical_padding),
            line_height + self._vertical_padding,
        )
        self.cell_width_px = max(
            int(base_font.measure("M") * 4 + self._horizontal_padding),
            self.cell_min_width,
        )

        self.wrapper = tk.Frame(parent, background=background, relief=tk.FLAT, bd=0)
        self.wrapper.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.grid = tk.Frame(self.wrapper, background=background)
        self.grid.pack(fill=tk.BOTH, expand=True)

        # Corner cell
        self.corner_frame = tk.Frame(
            self.grid,
            background=accent_color,
            height=self.cell_height_px,
            width=self.row_header_width,
        )
        self.corner_frame.grid(row=0, column=0, sticky="nsew")
        self._disable_geometry_propagation(self.corner_frame)
        self.corner_label = tk.Label(
            self.corner_frame,
            text=corner_title,
            font=("Segoe UI", 10, "bold"),
            background=accent_color,
            foreground="white",
            padx=12,
            pady=12,
            anchor="center",
            justify="center",
        )
        self.corner_label.pack(fill=tk.BOTH, expand=True)

        # Vertical divider separating headers from data
        self.vertical_divider = tk.Frame(self.grid, bg=accent_color, width=divider_thickness)
        self.vertical_divider.grid(row=0, column=1, rowspan=3, sticky="ns")

        # Column header canvas (top row)
        self.column_header_canvas = tk.Canvas(
            self.grid,
            background=background,
            highlightthickness=0,
            height=self.cell_height_px,
        )
        self.column_header_canvas.grid(row=0, column=2, sticky="nsew")

        # Horizontal divider separating headers from data
        self.horizontal_divider = tk.Frame(self.grid, bg=accent_color, height=divider_thickness)
        self.horizontal_divider.grid(row=1, column=0, columnspan=3, sticky="ew")

        # Row header canvas (left column)
        self.row_header_canvas = tk.Canvas(self.grid, background=background, highlightthickness=0, width=row_header_width)
        self.row_header_canvas.grid(row=2, column=0, sticky="nsew")

        # Data canvas (main grid)
        self.data_canvas = tk.Canvas(self.grid, background=background, highlightthickness=0)
        self.data_canvas.grid(row=2, column=2, sticky="nsew")

        # Scrollbars
        self.vertical_scrollbar = tk.Scrollbar(self.grid, orient=tk.VERTICAL, command=self._on_vertical_scroll)
        self.vertical_scrollbar.grid(row=2, column=3, sticky="ns")
        self.horizontal_scrollbar = tk.Scrollbar(self.grid, orient=tk.HORIZONTAL, command=self._on_horizontal_scroll)
        self.horizontal_scrollbar.grid(row=3, column=2, sticky="ew")

        # Configure scrolling links
        self.data_canvas.configure(
            xscrollcommand=self._sync_horizontal_scrollbar,
            yscrollcommand=self._sync_vertical_scrollbar,
        )

        # Frames hosted inside canvases
        self.column_header_frame = tk.Frame(self.column_header_canvas, background=background)
        self.column_header_window = self.column_header_canvas.create_window((0, 0), window=self.column_header_frame, anchor="nw")

        self.row_header_frame = tk.Frame(self.row_header_canvas, background=background)
        self.row_header_window = self.row_header_canvas.create_window((0, 0), window=self.row_header_frame, anchor="nw")

        self.data_frame = tk.Frame(self.data_canvas, background=background)
        self.data_window = self.data_canvas.create_window((0, 0), window=self.data_frame, anchor="nw")

        # Bind configure events to keep scroll regions updated
        self.column_header_frame.bind("<Configure>", self._on_column_header_frame_configure)
        self.row_header_frame.bind("<Configure>", self._on_row_header_frame_configure)
        self.data_frame.bind("<Configure>", self._on_data_frame_configure)

        self.column_header_canvas.bind("<Configure>", self._resize_column_header_window)
        self.row_header_canvas.bind("<Configure>", self._resize_row_header_window)
        self.data_canvas.bind("<Configure>", self._resize_data_window)

        # Mouse wheel bindings
        self.data_canvas.bind("<MouseWheel>", self._on_mousewheel_y)
        self.data_canvas.bind("<Shift-MouseWheel>", self._on_mousewheel_x)

        self.column_header_canvas.bind("<Shift-MouseWheel>", self._on_mousewheel_x)
        self.row_header_canvas.bind("<MouseWheel>", self._on_mousewheel_y)

        # Grid weights
        self.grid.columnconfigure(0, weight=0)
        self.grid.columnconfigure(2, weight=1)
        self.grid.rowconfigure(0, weight=0, minsize=self.cell_height_px)
        self.grid.rowconfigure(2, weight=1)

        self.data_cells: List[List[tk.Widget]] = []

    def build(
        self,
        *,
        row_headers: Sequence[str],
        column_headers: Sequence[str],
        column_colors: Sequence[str],
        row_header_factory: Optional[Callable[[int, str, tk.Frame], tk.Widget]] = None,
        column_header_factory: Optional[Callable[[int, str, tk.Frame, str], tk.Widget]] = None,
        cell_factory: Callable[[int, int, tk.Frame, str], tk.Widget],
    ) -> List[List[tk.Widget]]:
        """Populate the table with headers and data cells."""
        self._reset_region(self.column_header_frame)
        self._reset_region(self.row_header_frame)
        self._reset_region(self.data_frame)

        row_count = len(row_headers)
        column_count = len(column_headers)
        self.column_count = column_count

        self._configure_grid(row_count, column_count)
        self.row_header_widgets = self._build_row_headers(row_headers, row_header_factory)
        self.column_header_widgets = self._build_column_headers(column_headers, column_colors, column_header_factory)
        self.data_cells = self._build_data_cells(row_count, column_count, column_colors, cell_factory)

        return self.data_cells

    # --- Internal helpers -------------------------------------------------

    def _reset_region(self, frame: tk.Frame):
        for child in frame.winfo_children():
            child.destroy()

    def _configure_grid(self, row_count: int, column_count: int):
        for row_index in range(row_count):
            self.data_frame.grid_rowconfigure(row_index, weight=1)
            self.row_header_frame.grid_rowconfigure(row_index, weight=1, minsize=self.cell_height_px)
        for col_index in range(column_count):
            self.data_frame.grid_columnconfigure(col_index, weight=0, minsize=self.cell_width_px)
            self.column_header_frame.grid_columnconfigure(col_index, weight=0, minsize=self.cell_width_px)
        self.row_header_frame.grid_columnconfigure(0, weight=1, minsize=self.row_header_width)
        self.column_header_frame.grid_rowconfigure(0, weight=1, minsize=self.cell_height_px)

    def _build_row_headers(
        self,
        row_headers: Sequence[str],
        row_header_factory: Optional[Callable[[int, str, tk.Frame], tk.Widget]],
    ) -> List[tk.Widget]:
        widgets: List[tk.Widget] = []
        for row_index, text in enumerate(row_headers):
            frame = self._create_header_cell(
                self.row_header_frame,
                row_index,
                0,
                width=self.row_header_width,
                height=self.cell_height_px,
                lock_height=True,
            )
            frame.grid(row=row_index, column=0, sticky="nsew", pady=(0, 1))
            widget = row_header_factory(row_index, text, frame) if row_header_factory else None
            if widget is None:
                widget = self._default_row_header_widget(frame, text)
            widgets.append(widget)
        return widgets

    def _build_column_headers(
        self,
        column_headers: Sequence[str],
        column_colors: Sequence[str],
        column_header_factory: Optional[Callable[[int, str, tk.Frame, str], tk.Widget]],
    ) -> List[tk.Widget]:
        widgets: List[tk.Widget] = []
        for col_index, text in enumerate(column_headers):
            frame = self._create_header_cell(
                self.column_header_frame,
                0,
                col_index,
                width=self.cell_width_px,
                height=self.cell_height_px,
                lock_width=True,
            )
            frame.grid(row=0, column=col_index, sticky="nsew", padx=(0, 1))
            color = column_colors[col_index]
            widget = column_header_factory(col_index, text, frame, color) if column_header_factory else None
            if widget is None:
                widget = self._default_column_header_widget(frame, text, color)
            widgets.append(widget)
        return widgets

    def _build_data_cells(
        self,
        row_count: int,
        column_count: int,
        column_colors: Sequence[str],
        cell_factory: Callable[[int, int, tk.Frame, str], tk.Widget],
    ) -> List[List[tk.Widget]]:
        data_cells: List[List[tk.Widget]] = []
        for col_index in range(column_count):
            color = column_colors[col_index]
            column_widgets: List[tk.Widget] = []
            for row_index in range(row_count):
                frame = self._create_data_cell_frame(row_index, col_index, color)
                widget = cell_factory(row_index, col_index, frame, color)
                column_widgets.append(widget)
            data_cells.append(column_widgets)
        return data_cells

    def _create_header_cell(
        self,
        parent: tk.Frame,
        row: int,
        column: int,
        *,
        width: int,
        height: int,
        lock_width: bool = True,
        lock_height: bool = True,
    ) -> tk.Frame:
        frame = tk.Frame(
            parent,
            background="#f3f4f6",
            highlightthickness=1,
            highlightbackground=self.column_separator_color,
        )
        if lock_width:
            frame.configure(width=width)
        if lock_height:
            frame.configure(height=height)
        if lock_width or lock_height:
            self._disable_geometry_propagation(frame)
        return frame

    def _create_data_cell_frame(self, row: int, column: int, background: str) -> tk.Frame:
        frame = tk.Frame(
            self.data_frame,
            background=background,
            highlightthickness=1,
            highlightbackground=self.column_separator_color,
            width=self.cell_width_px,
            height=self.cell_height_px,
        )
        frame.grid(row=row, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))
        self._disable_geometry_propagation(frame)
        return frame

    def _default_row_header_widget(self, parent: tk.Frame, text: str) -> tk.Widget:
        label = tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 10, "bold"),
            background="#f3f4f6",
            foreground="#111827",
            wraplength=self.row_header_width - 16,
            justify="center",
        )
        label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        return label

    def _default_column_header_widget(self, parent: tk.Frame, text: str, color: str) -> tk.Widget:
        label = tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 10, "bold"),
            background=color,
            foreground="#111827",
            wraplength=self.cell_min_width - 16,
            justify="center",
        )
        label.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        return label

    def _disable_geometry_propagation(self, widget: tk.Widget):
        """Prevent children from changing the widget's requested size."""
        widget.grid_propagate(False)
        widget.pack_propagate(False)

    # --- Scroll + resize sync ---------------------------------------------

    def _on_column_header_frame_configure(self, event=None):
        self.column_header_canvas.configure(scrollregion=self.column_header_canvas.bbox("all"))

    def _on_row_header_frame_configure(self, event=None):
        bbox = self.row_header_canvas.bbox("all")
        if bbox:
            padding = max(self.horizontal_scrollbar.winfo_height(), 12)
            self.row_header_canvas.configure(scrollregion=(bbox[0], bbox[1], bbox[2], bbox[3] + padding))
        else:
            self.row_header_canvas.configure(scrollregion=bbox)

    def _on_data_frame_configure(self, event=None):
        bbox = self.data_canvas.bbox("all")
        if bbox:
            padding = max(self.horizontal_scrollbar.winfo_height(), 12)
            self.data_canvas.configure(scrollregion=(bbox[0], bbox[1], bbox[2], bbox[3] + padding))
        else:
            self.data_canvas.configure(scrollregion=bbox)

    def _resize_column_header_window(self, event=None):
        canvas_width = self.column_header_canvas.winfo_width()
        if canvas_width > 1:
            target_width = max(canvas_width, self._desired_table_width)
            self.column_header_canvas.itemconfigure(
                self.column_header_window,
                width=target_width,
                height=self.cell_height_px,
            )

    def _resize_row_header_window(self, event=None):
        canvas_width = self.row_header_canvas.winfo_width()
        if canvas_width > 1:
            self.row_header_canvas.itemconfigure(self.row_header_window, width=self.row_header_width)

    def _resize_data_window(self, event=None):
        canvas_width = self.data_canvas.winfo_width()
        if canvas_width > 1:
            target_width = max(canvas_width, self._desired_table_width)
            self.data_canvas.itemconfigure(self.data_window, width=target_width)

    @property
    def _desired_table_width(self) -> int:
        return max(self.cell_width_px * max(self.column_count, 1), self.cell_width_px)

    def _sync_horizontal_scrollbar(self, first: str, last: str):
        self.horizontal_scrollbar.set(first, last)
        self.column_header_canvas.xview_moveto(first)

    def _sync_vertical_scrollbar(self, first: str, last: str):
        self.vertical_scrollbar.set(first, last)
        self.row_header_canvas.yview_moveto(first)

    def _on_horizontal_scroll(self, *args):
        self.data_canvas.xview(*args)
        self.column_header_canvas.xview(*args)

    def _on_vertical_scroll(self, *args):
        self.data_canvas.yview(*args)
        self.row_header_canvas.yview(*args)

    def _on_mousewheel_y(self, event):
        self.data_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_mousewheel_x(self, event):
        self.data_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"
