import os
import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


from visualization.colreg_scenarios.components import (
    ActorControlComponent,
    ActorInfoComponent,
    ColregControlComponent,
    ManeuverMonitorInfoComponent,
    MonitorInfoComponent,
    TimeControlComponent,
    ToolbarComponent,
)
from visualization.colreg_scenarios.scenario_metrics_plot import ScenarioMetricsPlot
from visualization.colreg_scenarios.scenario_plot import ScenarioPlot


class ScenarioPlotManager:
    def __init__(self, trajectory_manager: TrajectoryManager):
        self.trajectory_manger = trajectory_manager
        self.colreg_plot = ScenarioPlot(trajectory_manager)
        self.metrics_plot = None
        self.root = tk.Tk()
        self.root.resizable(True, True)

        self.root.option_add("*Font", ("Times New Roman", 14))
        self.root.title("COLREG situation visualizer")

        # CANVAS FRAME
        self.canvas_frame = tk.Frame(master=self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        # PLOT FRAME
        self.plot_frame = tk.Frame(master=self.canvas_frame)
        self.plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = FigureCanvasTkAgg(self.colreg_plot.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # TOOLBAR FRAME
        self.toolbar_frame = tk.Frame(master=self.root, height=50)
        self.toolbar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.toolbar_frame.pack_propagate(False)

        # CONTROL FRAME
        self.control_frame = tk.Frame(master=self.canvas_frame, width=500, bg="#f0f0f0")
        self.control_frame.pack(side=tk.RIGHT, fill=tk.Y, expand=False)
        self.control_frame.pack_propagate(False)

        # Add resize handle for the control frame
        self._add_resize_handle()

        # Create main sections within the control frame
        self._create_control_sections()

        # Initialize components
        self._initialize_components()
        self.root.wait_window()

    def _add_resize_handle(self):
        """Add a resize handle to the left edge of the control frame."""
        # Create a thin frame on the left edge for resizing
        self.resize_handle = tk.Frame(self.control_frame, width=3, bg="#888888", cursor="sb_h_double_arrow")
        self.resize_handle.pack(side=tk.LEFT, fill=tk.Y)

        # Bind mouse events for resizing
        self.resize_handle.bind("<Button-1>", self._start_resize)
        self.resize_handle.bind("<B1-Motion>", self._do_resize)
        self.resize_handle.bind("<ButtonRelease-1>", self._stop_resize)

        # Add double-click to toggle collapse
        self.resize_handle.bind("<Double-Button-1>", self._toggle_control_panel)

        # Add hover effects
        self.resize_handle.bind("<Enter>", lambda e: self.resize_handle.configure(bg="#666666"))
        self.resize_handle.bind("<Leave>", lambda e: self.resize_handle.configure(bg="#888888"))

        # Store initial state
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._is_collapsed = False
        self._saved_width = 500
        self._right_pane_initialized = False
        self._left_pane_initialized = False
        self._vertical_resize_start_y = None
        self._vertical_sash_initial_y = None
        self._vertical_sash_x = None
        self._right_pane_initialized = False

    def _start_resize(self, event):
        """Start resizing the control frame."""
        self._resize_start_x = event.x_root
        self._resize_start_width = self.control_frame.winfo_width()

    def _do_resize(self, event):
        """Handle resizing of the control frame."""
        delta_x = event.x_root - self._resize_start_x
        # Allow expansion to full width (no maximum limit)
        new_width = max(200, self._resize_start_width - delta_x)  # Min 200px, no max limit
        self.control_frame.configure(width=new_width)

    def _stop_resize(self, event):
        """Stop resizing the control frame."""
        pass

    def _toggle_control_panel(self, event):
        """Toggle the control panel between collapsed and expanded states."""
        if self._is_collapsed:
            # Expand the panel
            self.control_frame.configure(width=self._saved_width)
            self._is_collapsed = False
        else:
            # Collapse the panel (save current width first)
            self._saved_width = self.control_frame.winfo_width()
            self.control_frame.configure(width=3)  # Just show the resize handle
            self._is_collapsed = True

    def _create_control_sections(self):
        """Create organized sections within the control frame."""
        # Time control section at the top
        self.time_section = tk.Frame(self.control_frame, bg="#e8f4f8", relief=tk.RAISED, bd=1)
        self.time_section.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # Main content area - simplified for now
        self.content_frame = tk.Frame(self.control_frame, bg="#f0f0f0")
        self.content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create resizable columns directly in content frame
        self._create_resizable_columns()

    def _create_resizable_columns(self):
        """Create horizontally resizable columns with a splitter and scrolling."""
        # Create a paned window for resizable columns
        self.paned_window = tk.PanedWindow(self.content_frame, orient=tk.HORIZONTAL, sashwidth=8, sashrelief=tk.RAISED, bg="#f0f0f0", handlesize=8)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        # Create scrollable left column
        self.left_column_frame, self.left_control_frame = self._create_scrollable_column(self.paned_window, "left")

        # Create scrollable right column
        self.right_column_frame, self.right_control_frame = self._create_scrollable_column(self.paned_window, "right")

        # Add the main column frames to paned window (not the scrollable frames)
        self.paned_window.add(self.left_column_frame, minsize=120)
        self.paned_window.add(self.right_column_frame, minsize=120)

        # Set initial proportions (50/50) by configuring the sash position
        # This will be done after the window is fully created
        self.root.after(100, self._set_initial_sash_position)

    def _create_scrollable_column(self, parent, column_name):
        """Create a scrollable column with canvas and scrollbar."""
        # Main frame for the column
        column_frame = tk.Frame(parent, bg="#f0f0f0", width=150)

        # Create canvas for scrolling
        canvas = tk.Canvas(column_frame, bg="#f0f0f0", highlightthickness=0)
        scrollbar = tk.Scrollbar(column_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#f0f0f0")

        # Configure scrollable frame
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind mousewheel to canvas (only when mouse is over this canvas)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)

        # Configure canvas window sizing
        def _configure_canvas_window(event=None):
            canvas_width = canvas.winfo_width()
            if canvas_width > 1:
                canvas.itemconfig(canvas_window, width=canvas_width)
            canvas_height = canvas.winfo_height()
            if canvas_height > 1:
                canvas.itemconfig(canvas_window, height=canvas_height)

        canvas.bind("<Configure>", _configure_canvas_window)

        # Store references for later use
        setattr(self, f"{column_name}_canvas", canvas)
        setattr(self, f"{column_name}_scrollable_frame", scrollable_frame)

        # Return both the main column frame (for paned window) and scrollable frame (for components)
        return column_frame, scrollable_frame

    def _set_initial_sash_position(self):
        """Set the initial sash position to create equal column widths."""
        try:
            # Get the paned window width and set sash to middle
            paned_width = self.paned_window.winfo_width()
            if paned_width > 1:  # Make sure the window is visible
                sash_position = paned_width // 2
                self.paned_window.sash_place(0, sash_position, 0)
        except tk.TclError:
            # If there's an error, try again later
            self.root.after(100, self._set_initial_sash_position)

    def _set_initial_right_pane_sash_position(self):
        """Set the initial sash position for the right column vertical splitter."""
        if not hasattr(self, "right_vertical_pane"):
            return
        if self._right_pane_initialized:
            return

        try:
            pane_height = self.right_vertical_pane.winfo_height()
            if pane_height > 1:
                sash_position = pane_height // 2
                self.right_vertical_pane.sash_place(0, 0, sash_position)
                self._right_pane_initialized = True
                coords = self.right_vertical_pane.sash_coord(0)
                if coords:
                    self._vertical_sash_x, self._vertical_sash_initial_y = coords
            else:
                self.root.after(100, self._set_initial_right_pane_sash_position)
        except tk.TclError:
            self.root.after(100, self._set_initial_right_pane_sash_position)

    def _on_right_vertical_pane_configure(self, event):
        """Ensure the splitter starts centered before user adjustments."""
        if not self._right_pane_initialized:
            self._set_initial_right_pane_sash_position()

    def _set_initial_left_pane_sash_positions(self):
        """Set initial sash positions for the left column vertical splitter."""
        if not hasattr(self, "left_vertical_pane"):
            return
        if self._left_pane_initialized:
            return

        try:
            pane_height = self.left_vertical_pane.winfo_height()
            if pane_height > 1:
                first_split = pane_height // 3
                second_split = (pane_height * 2) // 3
                self.left_vertical_pane.sash_place(0, 0, first_split)
                self.left_vertical_pane.sash_place(1, 0, second_split)
                self._left_pane_initialized = True
            else:
                self.root.after(100, self._set_initial_left_pane_sash_positions)
        except tk.TclError:
            self.root.after(100, self._set_initial_left_pane_sash_positions)

    def _on_left_vertical_pane_configure(self, event):
        """Ensure the left splitter initializes after layout."""
        if not self._left_pane_initialized:
            self._set_initial_left_pane_sash_positions()

    def _add_vertical_resize_handle(self, container: tk.Frame):
        """Create a draggable horizontal resize handle tied to the vertical sash."""
        handle = tk.Frame(container, height=6, bg="#888888", cursor="sb_v_double_arrow")
        handle.pack(side=tk.BOTTOM, fill=tk.X)
        handle.bind("<Button-1>", self._start_vertical_split_resize)
        handle.bind("<B1-Motion>", self._do_vertical_split_resize)
        handle.bind("<ButtonRelease-1>", self._stop_vertical_split_resize)
        handle.bind("<Enter>", lambda e: handle.configure(bg="#666666"))
        handle.bind("<Leave>", lambda e: handle.configure(bg="#888888"))

    def _start_vertical_split_resize(self, event):
        """Record starting state for vertical split resizing."""
        if not hasattr(self, "right_vertical_pane"):
            return
        coords = self.right_vertical_pane.sash_coord(0)
        if coords:
            self._vertical_sash_x, self._vertical_sash_initial_y = coords
        else:
            self._vertical_sash_x, self._vertical_sash_initial_y = 0, 0
        self._vertical_resize_start_y = event.y_root

    def _do_vertical_split_resize(self, event):
        """Resize the vertical split based on drag distance."""
        if self._vertical_resize_start_y is None:
            return

        delta_y = event.y_root - self._vertical_resize_start_y
        new_y = self._vertical_sash_initial_y + delta_y

        pane_height = self.right_vertical_pane.winfo_height()
        min_offset = 150
        max_offset = max(min_offset, pane_height - min_offset)
        new_y = max(min_offset, min(new_y, max_offset))

        self.right_vertical_pane.sash_place(0, self._vertical_sash_x, new_y)

    def _stop_vertical_split_resize(self, event):
        """Reset drag tracking and record last sash location."""
        if not hasattr(self, "right_vertical_pane"):
            return

        self._vertical_resize_start_y = None
        coords = self.right_vertical_pane.sash_coord(0)
        if coords:
            self._vertical_sash_x, self._vertical_sash_initial_y = coords

    def _initialize_components(self):
        """Initialize all UI components."""
        # Time control component in dedicated time section
        self.time_control_component = TimeControlComponent(self.time_section, self.trajectory_manger, self.colreg_plot)
        self.time_control_component.create_sliders_in_toolbar(self.toolbar_frame)

        # Left column components
        self._create_left_column_components()

        # Right column components
        self._create_right_column_components()

        # Toolbar component
        self.toolbar_component = ToolbarComponent(self.toolbar_frame, self.canvas, self.plot_frame)

        # Set up callbacks
        self.toolbar_component.on_plot_selection_callback = self._on_select_plot
        self.toolbar_component.on_exit_callback = self._exit_application
        self.toolbar_component.on_continue_callback = self._continue_application
        self.toolbar_component.on_hide_control_callback = self._hide_control

    def _create_left_column_components(self):
        """Create components for the left column."""
        print(f"Creating left column components in frame: {self.left_control_frame}")

        # Create a vertical paned window similar to the right column to host each component
        self.left_vertical_pane = tk.PanedWindow(
            self.left_control_frame,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            handlesize=8,
            bg="#f0f0f0",
            showhandle=True,
        )
        self.left_vertical_pane.pack(fill=tk.BOTH, expand=True)
        self.left_vertical_pane.bind("<Configure>", self._on_left_vertical_pane_configure)

        actor_info_container = tk.Frame(self.left_vertical_pane, bg="#f0f0f0")
        actor_control_container = tk.Frame(self.left_vertical_pane, bg="#f0f0f0")
        colreg_control_container = tk.Frame(self.left_vertical_pane, bg="#f0f0f0")

        for container in (actor_info_container, actor_control_container, colreg_control_container):
            self.left_vertical_pane.add(container, minsize=150)
            self.left_vertical_pane.paneconfigure(container, stretch="always")

        actor_info_wrapper = tk.Frame(actor_info_container, bg="#f0f0f0")
        actor_info_wrapper.pack(fill=tk.BOTH, expand=True)
        actor_control_wrapper = tk.Frame(actor_control_container, bg="#f0f0f0")
        actor_control_wrapper.pack(fill=tk.BOTH, expand=True)
        colreg_control_wrapper = tk.Frame(colreg_control_container, bg="#f0f0f0")
        colreg_control_wrapper.pack(fill=tk.BOTH, expand=True)

        # Actor info component
        self.actor_info_component = ActorInfoComponent(actor_info_wrapper, self.trajectory_manger, self.colreg_plot)
        print("Actor info component created")

        # Actor control component
        self.actor_control_component = ActorControlComponent(actor_control_wrapper, self.trajectory_manger, self.colreg_plot)
        print("Actor control component created")

        # COLREG control component
        self.colreg_control_component = ColregControlComponent(colreg_control_wrapper, self.trajectory_manger, self.colreg_plot)
        print("COLREG control component created")

        # Update scroll region after components are created
        self.root.after(100, lambda: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self.root.after(100, self._set_initial_left_pane_sash_positions)

    def _create_right_column_components(self):
        """Create components for the right column."""
        print(f"Creating right column components in frame: {self.right_control_frame}")

        # Create a vertical paned window to allow resizing between monitor components
        self.right_vertical_pane = tk.PanedWindow(
            self.right_control_frame,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            handlesize=8,
            bg="#f0f0f0",
            showhandle=True,
        )
        self.right_vertical_pane.pack(fill=tk.BOTH, expand=True)

        # Create containers for each component to add to the paned window
        maneuver_container = tk.Frame(self.right_vertical_pane, bg="#f0f0f0")
        monitor_container = tk.Frame(self.right_vertical_pane, bg="#f0f0f0")

        self.right_vertical_pane.add(maneuver_container, minsize=150)
        self.right_vertical_pane.add(monitor_container, minsize=150)
        self.right_vertical_pane.paneconfigure(maneuver_container, stretch="always")
        self.right_vertical_pane.paneconfigure(monitor_container, stretch="always")
        self.right_vertical_pane.bind("<Configure>", self._on_right_vertical_pane_configure)

        maneuver_wrapper = tk.Frame(maneuver_container, bg="#f0f0f0")
        maneuver_wrapper.pack(fill=tk.BOTH, expand=True)
        monitor_wrapper = tk.Frame(monitor_container, bg="#f0f0f0")
        monitor_wrapper.pack(fill=tk.BOTH, expand=True)

        # Maneuver monitor info component (above the monitor info component)
        self.maneuver_monitor_info_component = ManeuverMonitorInfoComponent(maneuver_wrapper, self.trajectory_manger, self.colreg_plot)
        print("Maneuver monitor info component created")
        self._add_vertical_resize_handle(maneuver_container)

        # Monitor info component
        self.monitor_info_component = MonitorInfoComponent(monitor_wrapper, self.trajectory_manger, self.colreg_plot)
        print("Monitor info component created")
        self._add_vertical_resize_handle(monitor_container)

        # Update scroll region after components are created
        self.root.after(100, lambda: self.right_canvas.configure(scrollregion=self.right_canvas.bbox("all")))
        # Set initial sash position after layout
        self._set_initial_right_pane_sash_position()

    def _exit_application(self):
        """Handle exit application."""
        if self.root and self.root.winfo_exists():
            self.root.destroy()
            self.root.quit()
        os._exit(0)

    def _continue_application(self):
        """Handle continue application."""
        if self.root and self.root.winfo_exists():
            self.root.destroy()
            self.root.quit()

    def _on_select_plot(self, value):
        """Handle plot selection change."""
        if value == "Scenario":
            plot = self.colreg_plot
        elif value == "Metrics":
            if self.metrics_plot is None:
                self.metrics_plot = ScenarioMetricsPlot(self.trajectory_manger)
            plot = self.metrics_plot
        else:
            raise Exception("Not implemented plot.")

        # Update canvas and navigation toolbar
        self.canvas.get_tk_widget().destroy()
        self.canvas = FigureCanvasTkAgg(plot.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.toolbar_component.update_navigation_toolbar(self.canvas)

    def _hide_control(self):
        """Toggle control panel visibility."""
        if self.toolbar_component.hide_button["text"] == "Hide control":
            self.control_frame.pack_forget()  # Hide the frame
            self.toolbar_component.set_hide_button_text("Show control")
        elif self.toolbar_component.hide_button["text"] == "Show control":
            self.control_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)
            self.toolbar_component.set_hide_button_text("Hide control")
