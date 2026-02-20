import subprocess
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, Select, Static, ProgressBar

from ..config import CURRENT_ALERT_THRESHOLD, CURRENT_WARN_THRESHOLD
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
            pid = self._launch(preset["duration"], preset["matrix"], preset["dtype"])
            self.dismiss((pid, preset_key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _launch(duration: int, matrix_size: int, dtype: str) -> int:
        script = (
            f"import torch, time; "
            f"d=torch.device('cuda'); "
            f"a=torch.randn({matrix_size},{matrix_size},dtype=torch.{dtype},device=d); "
            f"t=time.time(); "
            f"[torch.mm(a,a) for _ in iter(lambda: time.time()-t<{duration}, False)]"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.pid
