import os
import tkinter as tk
from datetime import datetime
from typing import Callable, Optional

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from utils.file_system_utils import EXPORTED_PLOTS_FOLDER


class ToolbarComponent:
    """Component responsible for toolbar controls including navigation, plot selection, and action buttons."""

    def __init__(self, parent_frame: tk.Frame, canvas: FigureCanvasTkAgg, plot_frame: tk.Frame):
        self.parent_frame = parent_frame
        self.canvas = canvas
        self.plot_frame = plot_frame

        # Toolbar frame
        self.toolbar_frame = tk.Frame(master=self.parent_frame, height=50)
        self.toolbar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.toolbar_frame.pack_propagate(False)

        # Navigation frame and toolbar
        self.navigation_frame = tk.Frame(self.toolbar_frame)
        self.navigation_frame.pack(fill=tk.BOTH, side=tk.LEFT)
        self.navigation_toolbar = NavigationToolbar2Tk(self.canvas, self.navigation_frame)
        self.navigation_toolbar.update()
        self.navigation_toolbar.pack(fill=tk.BOTH, side=tk.LEFT)

        # Plot selection dropdown
        self._create_plot_selection()

        # Action buttons
        self._create_action_buttons()

        # Callbacks for external components
        self.on_plot_selection_callback: Optional[Callable] = None
        self.on_exit_callback: Optional[Callable] = None
        self.on_continue_callback: Optional[Callable] = None
        self.on_hide_control_callback: Optional[Callable] = None

    def _create_plot_selection(self):
        """Create plot selection dropdown."""
        self.plot_options = ["Scenario", "Metrics"]
        self.selected_plot = tk.StringVar()
        self.selected_plot.set(self.plot_options[0])

        self.plot_dropdown = tk.OptionMenu(
            self.toolbar_frame,
            self.selected_plot,
            *self.plot_options,
            command=self._on_select_plot,
        )
        self.plot_dropdown.pack(side=tk.LEFT, padx=5)

    def _create_action_buttons(self):
        """Create action buttons."""
        # PDF export button
        self.to_pdf_button = tk.Button(self.toolbar_frame, text="PDF", command=self._to_pdf)
        self.to_pdf_button.pack(side=tk.LEFT, padx=5)

        # Hide control button
        self.hide_button = tk.Button(self.toolbar_frame, text="Hide control", command=self._hide_control)
        self.hide_button.pack(side=tk.LEFT, padx=5)

        # Exit and continue buttons
        self.exit_button = tk.Button(self.toolbar_frame, text="Exit", command=self._exit_application)
        self.exit_button.pack(side=tk.RIGHT, padx=5)

        self.continue_button = tk.Button(self.toolbar_frame, text="Continue", command=self._continue_application)
        self.continue_button.pack(side=tk.RIGHT, padx=5)

    def _on_select_plot(self, value):
        """Handle plot selection change."""
        if self.on_plot_selection_callback:
            self.on_plot_selection_callback(value)

    def _to_pdf(self):
        """Export current plot to PDF and SVG."""
        file_name = f'{self.selected_plot.get()}_{datetime.now().isoformat().replace(":","-")}'
        self.canvas.figure.savefig(
            f"{EXPORTED_PLOTS_FOLDER}/{file_name}.svg",
            format="svg",
            bbox_inches="tight",
            dpi=350,
        )
        self.canvas.figure.savefig(
            f"{EXPORTED_PLOTS_FOLDER}/{file_name}.pdf",
            format="pdf",
            bbox_inches="tight",
            dpi=350,
        )
        print("image saved")

    def _hide_control(self):
        """Toggle control panel visibility."""
        if self.on_hide_control_callback:
            self.on_hide_control_callback()

    def _exit_application(self):
        """Handle exit application."""
        if self.on_exit_callback:
            self.on_exit_callback()

    def _continue_application(self):
        """Handle continue application."""
        if self.on_continue_callback:
            self.on_continue_callback()

    def update_navigation_toolbar(self, new_canvas: FigureCanvasTkAgg):
        """Update the navigation toolbar for a new canvas."""
        self.navigation_toolbar.destroy()
        self.canvas = new_canvas
        self.navigation_toolbar = NavigationToolbar2Tk(self.canvas, self.navigation_frame)
        self.navigation_toolbar.update()
        self.navigation_toolbar.pack(fill=tk.BOTH, side=tk.LEFT)

    def set_hide_button_text(self, text: str):
        """Set the text of the hide control button."""
        self.hide_button.config(text=text)
