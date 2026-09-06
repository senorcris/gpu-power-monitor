import subprocess
import sys
import importlib.util
import asyncio
from rich.text import Text

from textual.app import ComposeResult
from textual import work
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static, ProgressBar

from ..config import CURRENT_ALERT_THRESHOLD, CURRENT_WARN_THRESHOLD, VOLTAGE_MIN, VOLTAGE_MAX
from ..gpu import PowerLimitConstraints
from ..protocol import PinReading


class TemperaturePanel(Static):
    """A compact thermal readout with redundant color and status cues."""

    DEFAULT_CSS = """
    TemperaturePanel {
        height: 5;
        padding: 0 1;
        border: round #728399;
        background: $surface;
    }
    TemperaturePanel.normal { border: round #5ed6a0; }
    TemperaturePanel.warm { border: round #f5c26b; }
    TemperaturePanel.hot { border: round #ff7b86; }
    """

    def on_mount(self) -> None:
        self.border_title = "Temperature"
        self.clear_reading()

    def clear_reading(self, message: str = "Waiting for GPU readings") -> None:
        self.remove_class("normal", "warm", "hot")
        self.tooltip = None
        self.update(Text(f"— °C\n{message}", style="dim"))

    def update_reading(self, temperature: float, profile: dict) -> None:
        warn, alarm = profile["temp_warn"], profile["temp_alarm"]
        state, label, color = (
            ("hot", "Hot · alert", "#ff7b86") if temperature >= alarm else
            ("warm", "Warm · warning", "#f5c26b") if temperature >= warn else
            ("normal", "Normal", "#5ed6a0")
        )
        self.remove_class("normal", "warm", "hot")
        self.add_class(state)
        text = Text()
        text.append(f"{temperature:g} °C", style=f"bold {color}")
        text.append(f"   ● {label}\n", style=color)
        filled = round(max(0, min(1, temperature / profile["max_temp_spec"])) * 16)
        text.append("━" * filled, style=f"bold {color}")
        text.append("━" * (16 - filled), style="dim")
        text.append(f"\nWarn {warn}° · Alert {alarm}°", style="dim")
        if temperature < warn:
            self.tooltip = f"{warn - temperature:g}° below warning"
        elif temperature < alarm:
            self.tooltip = f"{alarm - temperature:g}° below alert"
        else:
            self.tooltip = "At or above alert threshold"
        self.update(text)


def pin_status(pin: PinReading) -> str:
    if pin.current >= CURRENT_ALERT_THRESHOLD or (pin.voltage > 0 and not VOLTAGE_MIN <= pin.voltage <= VOLTAGE_MAX):
        return "ALERT"
    return "WARN" if pin.current >= CURRENT_WARN_THRESHOLD else "OK"


async def check_stress_support() -> tuple[bool, str]:
    """Check the child interpreter's CUDA support without allocating a workload."""
    if importlib.util.find_spec("torch") is None:
        return False, "PyTorch is missing in this tool environment. See README: Stress tests."
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=10)
    except (OSError, asyncio.TimeoutError) as e:
        return False, f"CUDA readiness check failed: {e}"
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
    if process.returncode:
        return False, "CUDA unavailable. Check the driver and install CUDA-enabled PyTorch."
    return True, "Ready: CUDA available. Start will allocate GPU memory."


class DetailsModal(ModalScreen):
    """Scrollable plain-text conditions and recovery guidance."""
    DEFAULT_CSS = """
    DetailsModal { align: center middle; }
    #details-dialog { width: 76; max-width: 100%; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 0 1; }
    #details-text { height: auto; }
    #details-close { width: 100%; }
    """
    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def compose(self):
        with VerticalScroll(id="details-dialog"):
            yield Static(self.text, markup=False, id="details-text")
            yield Button("Close [Esc]", id="details-close")

    def on_button_pressed(self, event):
        self.dismiss()

    def action_dismiss(self):
        self.dismiss()


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
        yield Static("-- A\n-- V\n-- W", classes="pin-stats")

    def update_reading(self, pin: PinReading) -> None:
        """Update the gauge with a new PinReading."""
        # Update progress bar (current as fraction of alert threshold)
        fraction = min(pin.current / CURRENT_ALERT_THRESHOLD, 1.0) if CURRENT_ALERT_THRESHOLD > 0 else 0
        bar = self.query_one(ProgressBar)
        bar.update(progress=fraction * 100)

        # Update stats text
        stats = self.query_one(".pin-stats", Static)
        stats.update(f"{pin.current:.2f}A\n{pin.voltage:.2f}V\n{pin.power:.1f}W")
        state = pin_status(pin)
        self.query_one(".pin-label", Static).update(f"{self._label} {state}")

        # Update border color class
        self.remove_class("warn", "alert")
        if state == "ALERT":
            self.add_class("alert")
        elif state == "WARN":
            self.add_class("warn")


_STRESS_PRESETS = {
    "quick": {"label": "Quick Test", "desc": "30 seconds, low VRAM", "duration": 30, "matrix": 4096, "dtype": "float32"},
    "standard": {"label": "Standard Test", "desc": "3 minutes, moderate load", "duration": 180, "matrix": 8192, "dtype": "float32"},
    "heavy": {"label": "Heavy Burn-in", "desc": "10 minutes, high VRAM", "duration": 600, "matrix": 16384, "dtype": "float16"},
}


class StressTestModal(ModalScreen[tuple[subprocess.Popen, str] | None]):
    """Modal dialog for launching a GPU stress test with simple presets.

    Dismisses with (process, preset_key) on start, or None on cancel.
    """

    DEFAULT_CSS = """
    StressTestModal {
        align: center middle;
    }
    #stress-dialog {
        width: 52;
        max-width: 100%;
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
    #stress-readiness { height: auto; margin: 1 0; }
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
                "Stop it from Processes [bold]x[/bold], then [bold]k[/bold].",
                classes="stress-desc",
            )
            yield Select(options, value="standard", id="stress-preset")
            yield Static("Checking PyTorch and CUDA…", id="stress-readiness", markup=False)
            with Horizontal(id="stress-buttons"):
                yield Button("Start", variant="success", id="stress-start", disabled=True)
                yield Button("Cancel", variant="error", id="stress-cancel")

    def on_mount(self) -> None:
        self._check_readiness()

    @work(exclusive=True)
    async def _check_readiness(self) -> None:
        ready, reason = await check_stress_support()
        if self.is_mounted:
            self.query_one("#stress-readiness", Static).update(reason)
            self.query_one("#stress-start", Button).disabled = not ready

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stress-cancel":
            self.dismiss(None)
            return

        if event.button.id == "stress-start":
            if event.button.disabled:
                return
            select = self.query_one("#stress-preset", Select)
            preset_key = select.value if select.value != Select.BLANK else "standard"
            preset = _STRESS_PRESETS[preset_key]
            try:
                popen = self._launch(preset["duration"], preset["matrix"], preset["dtype"])
            except OSError as e:
                self.query_one("#stress-readiness", Static).update(f"Could not start: {e}")
                return
            self.dismiss((popen, preset_key))

    def action_cancel(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _launch(duration: int, matrix_size: int, dtype: str) -> subprocess.Popen:
        script = (
            "import torch, time\n"
            "d=torch.device('cuda')\n"
            f"a=torch.randn({matrix_size},{matrix_size},dtype=torch.{dtype},device=d)\n"
            "print('GPU_POWER_MONITOR_RUNNING', flush=True)\n"
            "t=time.monotonic()\n"
            f"while time.monotonic()-t<{duration}:\n"
            "    torch.mm(a,a)\n"
            "    torch.cuda.synchronize()\n"
        )
        return subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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
        width: 60;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        border: thick $accent;
        background: $surface;
        padding: 0 1;
    }
    #pl-dialog .pl-heading {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 0;
    }
    #pl-dialog .pl-info {
        text-align: center;
        width: 100%;
        color: $text-muted;
        margin-bottom: 0;
    }
    #pl-dialog Input {
        width: 100%;
        margin-bottom: 0;
    }
    #pl-presets {
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 3 3;
        height: 6;
        width: 100%;
        margin-bottom: 0;
    }
    #pl-presets Button {
        width: 100%;
        min-width: 0;
        margin: 0;
    }
    #pl-buttons {
        height: auto;
        width: 100%;
        margin-top: 0;
    }
    #pl-buttons Button {
        width: 1fr;
        min-width: 0;
        margin: 0 1;
    }
    #pl-preview { height: 1; }
    #pl-error { height: 2; color: $error; }
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
                f"Range: {c.min_watts:.0f}W – {c.max_watts:.0f}W (NVIDIA permission required)",
                classes="pl-info",
            )
            yield Input(
                value=str(int(self._current_limit)),
                placeholder=f"{c.min_watts:.0f}–{c.max_watts:.0f}",
                type="integer",
                id="pl-input",
            )
            with Grid(id="pl-presets"):
                yield Button(f"Default ({c.default_watts:.0f}W)", id="pl-preset-100")
                for pct in (80, 70, 60):
                    watts = int(c.default_watts * pct / 100)
                    yield Button(f"{pct}% ({watts}W)", id=f"pl-preset-{pct}",
                                 disabled=not c.min_watts <= watts <= c.max_watts)
            yield Static("", id="pl-preview", markup=False)
            yield Static("", id="pl-error", markup=False)
            with Horizontal(id="pl-buttons"):
                yield Button("Apply", variant="success", id="pl-apply")
                yield Button("Cancel", variant="error", id="pl-cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "pl-input":
            return
        self.query_one("#pl-preview", Static).update(
            f"Apply change: {self._current_limit:.0f}W → {event.value or '?'}W"
        )
        self.query_one("#pl-error", Static).update("")

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
                watts = int(self.query_one("#pl-input", Input).value)
            except ValueError:
                self.query_one("#pl-error", Static).update("Enter a whole number of watts.")
                self.query_one("#pl-input", Input).focus()
                return
            if not c.min_watts <= watts <= c.max_watts:
                self.query_one("#pl-error", Static).update(
                    f"Enter {c.min_watts:.0f}–{c.max_watts:.0f}W. Nothing has been changed."
                )
                self.query_one("#pl-input", Input).focus()
                return
            self.dismiss(watts)

    def action_cancel(self) -> None:
        self.dismiss(None)
