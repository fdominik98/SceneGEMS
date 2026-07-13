import tkinter as tk
from typing import Callable


from visualization.colreg_scenarios.scenario_plot import ScenarioPlot


class TimeControlComponent:
    """Component responsible for time-related UI controls including sliders and time display."""

    def __init__(self, parent_frame: tk.Frame, trajectory_manager: TrajectoryManager, colreg_plot: ScenarioPlot):
        self.parent_frame = parent_frame
        self.colreg_plot = colreg_plot
        self.trajectory_manager = trajectory_manager

        # Flag to prevent circular updates
        self._updating_slider = False

        # Time control frame
        self.time_control_frame = tk.Frame(self.parent_frame, background="#e8f4f8")
        self.time_control_frame.pack(side=tk.TOP, fill=tk.X, pady=5, padx=5)

        # Add title
        title_label = tk.Label(self.time_control_frame, text="Animation Controls", font=("Arial", 10, "bold"), background="#e8f4f8")
        title_label.pack(side=tk.TOP, pady=(5, 5))

        # Time display label (will be moved under sliders)
        self.time_label = tk.Label(
            master=self.time_control_frame,
            text=self.colreg_plot.animation.sim_time_count,
            background="#e8f4f8",
            font=("Arial", 9),
        )

        # Create speed up slider (1x to 120x)
        self.speed_up_slider = self._create_slider("Speed:", 1, 240, self.colreg_plot.animation.speed_up_value, 1, self._get_speed_up)

        # Animation time_step slider (for setting exact time)
        self.animation_time_step_slider = self._create_slider("Animation Time:", 0, int(trajectory_manager.timespan), 0, 1, self._get_animation_time_step)

        # Start time updates
        self.update_sim_time()

    def _create_slider(self, label_text: str, min_val: int, max_val: int, init_val: int, step_value: int, command: Callable):
        """Create a slider with label in the toolbar frame."""
        # Note: This assumes the toolbar frame is accessible from parent
        # The actual slider creation will be handled by the parent component
        return {
            "label": label_text,
            "min_val": min_val,
            "max_val": max_val,
            "init_val": init_val,
            "step_value": step_value,
            "command": command,
        }

    def _get_speed_up(self, event):
        """Handle speed up slider changes."""
        if hasattr(self, "speed_up_slider_widget"):
            # Update speed value
            new_speed = self.speed_up_slider_widget.get()
            self.colreg_plot.animation.set_speed_up_value(new_speed)

    def _get_animation_time_step(self, event):
        """Handle animation time_step slider changes."""
        # Skip if this is a programmatic update
        if self._updating_slider:
            return

        if hasattr(self, "animation_time_step_slider_widget"):
            target_sim_time = self.animation_time_step_slider_widget.get()
            # Use the animation's built-in method to jump to a specific time
            self.colreg_plot.animation.set_current_sim_time(target_sim_time)
            self.colreg_plot.animation.update_monitored_scene()

    def update_sim_time(self):
        """Update the time display label and animation time_step slider."""
        if not self.time_control_frame.winfo_exists():
            return

        # Fetch new data
        self.time_label.config(text=self.colreg_plot.animation.sim_time_count)

        # Update animation timestep slider to match current time
        if hasattr(self, "animation_time_step_slider_widget"):
            current_time = int(self.colreg_plot.animation.current_sim_time)
            # Set flag to prevent triggering the callback
            self._updating_slider = True
            self.animation_time_step_slider_widget.set(current_time)
            self._updating_slider = False

        # Schedule the next update
        self.time_control_frame.after(150, self.update_sim_time)

    def _step_back(self):
        """Step back in the animation by the speed_up value."""
        if hasattr(self, "animation_time_step_slider_widget"):
            current_time = int(self.colreg_plot.animation.current_sim_time)
            speed_up = self.colreg_plot.animation.speed_up_value
            new_time = max(0, current_time - int(speed_up))

            # Update the slider which will trigger the animation update
            # Don't set the flag here - we want this to trigger the callback
            self.animation_time_step_slider_widget.set(new_time)
            self.colreg_plot.animation.set_current_sim_time(new_time)
            self.colreg_plot.animation.update_monitored_scene()

    def _step_forward(self):
        """Step forward in the animation by the speed_up value."""
        if hasattr(self, "animation_time_step_slider_widget"):
            current_time = int(self.colreg_plot.animation.current_sim_time)
            speed_up = self.colreg_plot.animation.speed_up_value
            max_time = int(self.trajectory_manager.timespan)
            new_time = min(max_time, current_time + int(speed_up))

            # Update the slider which will trigger the animation update
            # Don't set the flag here - we want this to trigger the callback
            self.animation_time_step_slider_widget.set(new_time)
            self.colreg_plot.animation.set_current_sim_time(new_time)
            self.colreg_plot.animation.update_monitored_scene()

    def _toggle_play_pause(self):
        """Toggle the animation between playing and paused states."""
        import time

        animation = self.colreg_plot.animation

        if animation.is_anim_paused:
            # Start the animation
            if animation.anim is None:
                animation.start()
            # Start the wall-clock timer when animation starts
            if animation.animation_start_time is None:
                animation.set_animation_start_time(time.time())
            animation.is_anim_paused = False
            self.play_pause_button.config(text="⏸")
        else:
            # Pause the animation
            animation.is_anim_paused = True
            self.play_pause_button.config(text="▶")

    def _reset_animation(self):
        """Reset the animation to the beginning."""
        # Use the animation's built-in reset method
        self.colreg_plot.animation.reset()

        # Update UI
        if hasattr(self, "play_pause_button"):
            self.play_pause_button.config(text="▶")

    def _update_button_states(self):
        """Update button states based on animation state."""
        if not self.time_control_frame.winfo_exists():
            return

        # Update play/pause button icon based on animation state
        if hasattr(self, "play_pause_button"):
            if self.colreg_plot.animation.is_anim_paused:
                self.play_pause_button.config(text="▶")
            else:
                self.play_pause_button.config(text="⏸")

        # Schedule the next update
        self.time_control_frame.after(250, self._update_button_states)

    def create_sliders_in_toolbar(self, toolbar_frame: tk.Frame):
        """Create the actual slider widgets in the toolbar frame."""
        # Navigation buttons frame
        nav_buttons_frame = tk.Frame(toolbar_frame)
        nav_buttons_frame.pack(side=tk.LEFT, padx=10)

        # Step back button
        self.step_back_button = tk.Button(nav_buttons_frame, text="⏮", font=("Arial", 14), width=3, command=self._step_back, relief=tk.RAISED, bd=2)
        self.step_back_button.pack(side=tk.LEFT, padx=2)

        # Play/Pause button
        self.play_pause_button = tk.Button(
            nav_buttons_frame,
            text="▶",
            font=("Arial", 14),
            width=3,
            command=self._toggle_play_pause,
            relief=tk.RAISED,
            bd=2,
        )
        self.play_pause_button.pack(side=tk.LEFT, padx=2)

        # Reset button
        self.reset_button = tk.Button(
            nav_buttons_frame,
            text="↺",
            font=("Arial", 14),
            width=3,
            command=self._reset_animation,
            relief=tk.RAISED,
            bd=2,
        )
        self.reset_button.pack(side=tk.LEFT, padx=2)

        # Step forward button
        self.step_forward_button = tk.Button(nav_buttons_frame, text="⏭", font=("Arial", 14), width=3, command=self._step_forward, relief=tk.RAISED, bd=2)
        self.step_forward_button.pack(side=tk.LEFT, padx=2)

        # Animation timestep slider (long slider for exact time control)
        anim_time_label = tk.Label(toolbar_frame, text=self.animation_time_step_slider["label"])
        anim_time_label.pack(side=tk.LEFT)

        self.animation_time_step_slider_widget = tk.Scale(
            toolbar_frame,
            from_=self.animation_time_step_slider["min_val"],
            to=self.animation_time_step_slider["max_val"],
            orient="horizontal",
            resolution=self.animation_time_step_slider["step_value"],
            command=self.animation_time_step_slider["command"],
            length=300,  # Make it longer
        )
        self.animation_time_step_slider_widget.set(self.animation_time_step_slider["init_val"])
        self.animation_time_step_slider_widget.pack(fill=tk.BOTH, side=tk.LEFT)

        # Speed up slider
        speed_up_label = tk.Label(toolbar_frame, text=self.speed_up_slider["label"])
        speed_up_label.pack(side=tk.LEFT)

        self.speed_up_slider_widget = tk.Scale(
            toolbar_frame,
            from_=self.speed_up_slider["min_val"],
            to=self.speed_up_slider["max_val"],
            orient="horizontal",
            resolution=self.speed_up_slider["step_value"],
            command=self.speed_up_slider["command"],
        )
        self.speed_up_slider_widget.set(self.speed_up_slider["init_val"])
        self.speed_up_slider_widget.pack(fill=tk.BOTH, side=tk.LEFT)

        # Add time display label under the sliders
        self.time_label.pack(side=tk.LEFT, padx=10)

        # Start updating button states
        self._update_button_states()
