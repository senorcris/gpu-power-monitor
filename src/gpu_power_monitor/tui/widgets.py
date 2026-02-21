import subprocess
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static, ProgressBar

from ..config import CURRENT_ALERT_THRESHOLD, CURRENT_WARN_THRESHOLD
from ..gpu import PowerLimitConstraints
from ..protocol import PinReading


class PinGauge(Widget):
    """Displays a single pin's voltage, current, and power readings."""

    DEFAULT_CSS = """
    PinGauge {
        width: 1fr;
        height: auto;
        border: solid green;
        padding: 0 1;
    }
    PinGauge.warn {
        border: solid yellow;
    }
    PinGauge.alert {
        border: solid red;
    }
    PinGauge .pin-label {
        text-style: bold;
        text-align: center;
        width: 100%;
    }
    PinGauge ProgressBar {
        width: 100%;
    }
    PinGauge .pin-stats {
        text-align: center;
        width: 100%;
    }
    """

    def __init__(self, pin_number: int, **kwargs):
        super().__init__(**kwargs)
        self.pin_number = pin_number
        self._label = f"Pin {pin_number}"

    def compose(self):
        yield Static(self._label, classes="pin-label")
        yield ProgressBar(total=100, show_eta=False, show_percentage=False)
        yield Static("-- A  -- V  -- W", classes="pin-stats")

    def update_reading(self, pin: PinReading) -> None:
        """Update the gauge with a new PinReading."""
        # Update progress bar (current as fraction of alert threshold)
        fraction = min(pin.current / CURRENT_ALERT_THRESHOLD, 1.0) if CURRENT_ALERT_THRESHOLD > 0 else 0
        bar = self.query_one(ProgressBar)
        bar.update(progress=fraction * 100)

        # Update stats text
        stats = self.query_one(".pin-stats", Static)
        stats.update(f"{pin.current:.2f}A  {pin.voltage:.2f}V  {pin.power:.1f}W")

        # Update border color class
        self.remove_class("warn", "alert")
        if pin.current >= CURRENT_ALERT_THRESHOLD:
            self.add_class("alert")
        elif pin.current >= CURRENT_WARN_THRESHOLD:
            self.add_class("warn")


_STRESS_PRESETS = {
    "quick": {"label": "Quick Test", "desc": "30 seconds, low VRAM", "duration": 30, "matrix": 4096, "dtype": "float32"},
    "standard": {"label": "Standard Test", "desc": "3 minutes, moderate load", "duration": 180, "matrix": 8192, "dtype": "float32"},
    "heavy": {"label": "Heavy Burn-in", "desc": "10 minutes, high VRAM", "duration": 600, "matrix": 16384, "dtype": "float16"},
}


class StressTestModal(ModalScreen[tuple[int, str] | None]):
    """Modal dialog for launching a GPU stress test with simple presets.

    Dismisses with (pid, preset_key) on start, or None on cancel.
    """

    DEFAULT_CSS = """
    StressTestModal {
        align: center middle;
    }
    #stress-dialog {
        width: 52;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #stress-dialog .stress-heading {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #stress-dialog .stress-desc {
        text-align: center;
        width: 100%;
        color: $text-muted;
        margin-bottom: 1;
    }
    #stress-dialog Select {
        width: 100%;
        margin-bottom: 1;
    }
    #stress-buttons {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    #stress-buttons Button {
        width: 1fr;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        options = [
            (f"{p['label']}  —  {p['desc']}", key)
            for key, p in _STRESS_PRESETS.items()
        ]
        with Vertical(id="stress-dialog"):
            yield Label("GPU Stress Test", classes="stress-heading")
            yield Label(
                "Runs matrix multiplication on your GPU.\n"
                "Process appears in the list — kill with [bold]k[/bold].",
                classes="stress-desc",
            )
            yield Select(options, value="standard", id="stress-preset")
            with Horizontal(id="stress-buttons"):
                yield Button("Start", variant="success", id="stress-start")
                yield Button("Cancel", variant="error", id="stress-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stress-cancel":
            self.dismiss(None)
            return

        if event.button.id == "stress-start":
            select = self.query_one("#stress-preset", Select)
            preset_key = select.value if select.value != Select.BLANK else "standard"
            preset = _STRESS_PRESETS[preset_key]
            popen = self._launch(preset["duration"], preset["matrix"], preset["dtype"])
            self.dismiss((popen, preset_key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _launch(duration: int, matrix_size: int, dtype: str) -> subprocess.Popen:
        script = (
            f"import torch, time; "
            f"d=torch.device('cuda'); "
            f"a=torch.randn({matrix_size},{matrix_size},dtype=torch.{dtype},device=d); "
            f"t=time.time(); "
            f"[torch.mm(a,a) for _ in iter(lambda: time.time()-t<{duration}, False)]"
        )
        return subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class PowerLimitModal(ModalScreen[float | None]):
    """Modal dialog for setting GPU power limit.

    Dismisses with the target wattage, or None on cancel.
    """

    DEFAULT_CSS = """
    PowerLimitModal {
        align: center middle;
    }
    #pl-dialog {
        width: 56;
        height: auto;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #pl-dialog .pl-heading {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #pl-dialog .pl-info {
        text-align: center;
        width: 100%;
        color: $text-muted;
        margin-bottom: 1;
    }
    #pl-dialog Input {
        width: 100%;
        margin-bottom: 1;
    }
    #pl-presets {
        height: auto;
        width: 100%;
        margin-bottom: 1;
    }
    #pl-presets Button {
        width: 1fr;
        margin: 0 1;
    }
    #pl-buttons {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    #pl-buttons Button {
        width: 1fr;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        constraints: PowerLimitConstraints,
        current_limit: float,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._constraints = constraints
        self._current_limit = current_limit

    def compose(self) -> ComposeResult:
        c = self._constraints
        with Vertical(id="pl-dialog"):
            yield Label("Set Power Limit", classes="pl-heading")
            yield Label(
                f"Current: {self._current_limit:.0f}W  |  "
                f"Default: {c.default_watts:.0f}W\n"
                f"Range: {c.min_watts:.0f}W – {c.max_watts:.0f}W\n"
                f"Requires root / sudo",
                classes="pl-info",
            )
            yield Input(
                value=str(int(self._current_limit)),
                placeholder=f"{c.min_watts:.0f}–{c.max_watts:.0f}",
                type="integer",
                id="pl-input",
            )
            with Horizontal(id="pl-presets"):
                yield Button(f"Default ({c.default_watts:.0f}W)", id="pl-preset-100")
                yield Button(f"80% ({c.default_watts * 0.8:.0f}W)", id="pl-preset-80")
                yield Button(f"70% ({c.default_watts * 0.7:.0f}W)", id="pl-preset-70")
                yield Button(f"60% ({c.default_watts * 0.6:.0f}W)", id="pl-preset-60")
            with Horizontal(id="pl-buttons"):
                yield Button("Apply", variant="success", id="pl-apply")
                yield Button("Cancel", variant="error", id="pl-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "pl-cancel":
            self.dismiss(None)
            return

        c = self._constraints
        if bid and bid.startswith("pl-preset-"):
            pct = int(bid.split("-")[-1])
            watts = c.default_watts * (pct / 100)
            self.query_one("#pl-input", Input).value = str(int(watts))
            return

        if bid == "pl-apply":
            try:
                watts = float(self.query_one("#pl-input", Input).value)
            except ValueError:
                self.notify("Enter a valid number", severity="error")
                return
            watts = max(c.min_watts, min(c.max_watts, watts))
            self.dismiss(watts)

    def action_cancel(self) -> None:
        self.dismiss(None)
