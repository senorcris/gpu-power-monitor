from textual.widgets import Static, ProgressBar
from textual.widget import Widget
from textual.containers import Vertical

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
