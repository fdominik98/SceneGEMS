import tkinter as tk
from typing import List, Optional

from matplotlib import pyplot as plt


class StandaloneCheckbox:
    """A standalone checkbox that controls matplotlib artists visibility."""

    def __init__(
        self,
        master,
        artists: List[plt.Artist],
        color,
        init_checked: bool,
        fig: Optional[plt.Figure] = None,
        text="",
    ):
        self.artists = artists
        self.text = text
        self.fig = fig
        self.value = tk.BooleanVar(master=master, value=init_checked)
        self.checkbox = tk.Checkbutton(
            master,
            variable=self.value,
            onvalue=True,
            text=text,
            offvalue=False,
            command=self.on_click,
            background=color,
        )
        self.checkbox.pack(side=tk.TOP, anchor="w", fill=tk.NONE)
        self.set_state(init_checked)

    def on_click(self):
        """Handle checkbox click event."""
        if self.fig is not None:
            self.set_state(self.value.get())
            self.fig.canvas.draw()

    def set_state(self, state: bool):
        """Set the visibility state of controlled artists."""
        self.value.set(state)
        for artist in self.artists:
            artist.set_visible(state)


class CheckboxArray:
    """A checkbox that controls multiple other checkboxes."""

    def __init__(self, master, text: str, fig: plt.Figure):
        self.fig = fig
        self.managed_checkboxes: List["Checkbox"] = []
        self.value = tk.BooleanVar(master=master, value=False)
        self._pending_draw = False
        self.checkbox = tk.Checkbutton(
            master,
            text=text,
            variable=self.value,
            onvalue=True,
            offvalue=False,
            command=self.on_click,
            background="grey",
        )
        self.checkbox.pack(side=tk.TOP, anchor="w")

    def add(self, checkbox: "Checkbox"):
        """Add a checkbox to be managed by this array."""
        self.managed_checkboxes.append(checkbox)
        self.notify(draw=False)

    def flush(self):
        """Trigger a delayed draw if there is one pending."""
        if not self._pending_draw:
            return
        canvas = getattr(self.fig, "canvas", None)
        if canvas is None:
            self._pending_draw = False
            return
        draw_fn = getattr(canvas, "draw_idle", None) or getattr(canvas, "draw", None)
        draw_fn()
        self._pending_draw = False

    def on_click(self):
        """Handle checkbox array click event."""
        state = self.value.get()
        for cb in self.managed_checkboxes:
            cb.set_state(state)
        self.fig.canvas.draw()

    def notify(self, *, draw: bool = True):
        """Update the checkbox array state based on managed checkboxes."""
        if not self.managed_checkboxes:
            return
        all_false = all(not cb.value.get() for cb in self.managed_checkboxes)
        self.value.set(not all_false)
        if draw:
            self.fig.canvas.draw()
            self._pending_draw = False
        else:
            self._pending_draw = True


class Checkbox(StandaloneCheckbox):
    """A checkbox that is managed by a CheckboxArray."""

    def __init__(
        self,
        master,
        artists: List[plt.Artist],
        checkbox_array: CheckboxArray,
        color: str,
        init_checked: bool,
    ):
        super().__init__(master, artists, color, init_checked)
        self.checkbox_array = checkbox_array
        self.checkbox_array.add(self)

    def on_click(self):
        """Handle checkbox click event and notify the array."""
        self.set_state(self.value.get())
        self.checkbox_array.notify()
