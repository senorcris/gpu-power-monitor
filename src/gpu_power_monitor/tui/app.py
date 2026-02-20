import asyncio
import logging
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Header, Static, RichLog
from textual import work

from ..config import (
    I2C_BUS, I2C_ADDRESS, I2C_REGISTER,
    REFRESH_INTERVAL, NUM_PINS, get_socket_path,
)
from ..protocol import MonitorSnapshot
from .widgets import PinGauge

logger = logging.getLogger(__name__)


class GpuPowerMonitorApp(App):
    """TUI for monitoring GPU 12V-2x6 connector power delivery."""

    TITLE = "GPU Power Monitor - 12V-2x6 Connector"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "clear_log", "Clear Log"),
    ]

    DEFAULT_CSS = """
    Screen {
        layout: vertical;
    }
    #pin-row {
        height: auto;
        width: 100%;
    }
    #summary {
        height: 1;
        width: 100%;
        text-align: center;
        text-style: bold;
    }
    #gpu-stats {
        height: 1;
        width: 100%;
        text-align: center;
    }
    #alert-log {
        height: 1fr;
        border: solid $accent;
    }
    """

    def __init__(self, bus=None, address=None, register=None, **kwargs):
        super().__init__(**kwargs)
        self._i2c_bus = bus if bus is not None else I2C_BUS
        self._i2c_address = address if address is not None else I2C_ADDRESS
        self._i2c_register = register if register is not None else I2C_REGISTER

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="pin-row"):
            for i in range(1, NUM_PINS + 1):
                yield PinGauge(pin_number=i, id=f"pin-{i}")
        yield Static("Total: -- A  -- W  |  Avg Voltage: -- V", id="summary")
        yield Static("GPU: --", id="gpu-stats")
        yield RichLog(id="alert-log", markup=True, wrap=True)

    def on_mount(self) -> None:
        self._start_reader()

    @work(exclusive=True, thread=True)
    def _start_reader(self) -> None:
        """Background thread: try daemon socket, fall back to direct reads."""
        import time

        socket_path = get_socket_path()

        # Try daemon socket first
        try:
            import socket as sock_mod
            s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            s.connect(socket_path)
            logger.info("Connected to daemon socket")
            buf = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line:
                            try:
                                snap = MonitorSnapshot.from_json(line.decode())
                                self.call_from_thread(self._apply_snapshot, snap)
                            except Exception as e:
                                logger.debug(f"Bad snapshot: {e}")
            finally:
                s.close()
        except (OSError, ConnectionRefusedError, FileNotFoundError):
            logger.info("Daemon not available, falling back to direct reads")

        # Direct polling fallback
        from ..i2c import IT8915Reader
        from ..gpu import GpuMonitor
        from ..config import CURRENT_ALERT_THRESHOLD, CURRENT_WARN_THRESHOLD

        i2c_reader = IT8915Reader(
            bus=self._i2c_bus,
            address=self._i2c_address,
            register=self._i2c_register,
        )
        gpu_mon = GpuMonitor()

        try:
            i2c_reader.open()
        except Exception as e:
            logger.warning(f"Could not open I2C bus: {e}")
        try:
            gpu_mon.open()
        except Exception as e:
            logger.warning(f"Could not open GPU monitor: {e}")

        try:
            while True:
                try:
                    connector = i2c_reader.read_pins()
                except Exception:
                    connector = None
                try:
                    gpu = gpu_mon.read_stats()
                except Exception:
                    gpu = None

                snap = MonitorSnapshot(connector=connector, gpu=gpu)
                if connector:
                    for pin in connector.pins:
                        if pin.current >= CURRENT_ALERT_THRESHOLD:
                            snap.alerts.append(
                                f"ALERT: {pin.label} current {pin.current:.2f}A exceeds {CURRENT_ALERT_THRESHOLD}A limit"
                            )
                        elif pin.current >= CURRENT_WARN_THRESHOLD:
                            snap.alerts.append(
                                f"WARN: {pin.label} current {pin.current:.2f}A exceeds {CURRENT_WARN_THRESHOLD}A warning"
                            )

                self.call_from_thread(self._apply_snapshot, snap)
                time.sleep(REFRESH_INTERVAL)
        finally:
            i2c_reader.close()
            gpu_mon.close()

    def _apply_snapshot(self, snap: MonitorSnapshot) -> None:
        """Update all widgets from a MonitorSnapshot."""
        if snap.connector:
            for pin in snap.connector.pins:
                try:
                    gauge = self.query_one(f"#pin-{pin.pin}", PinGauge)
                    gauge.update_reading(pin)
                except Exception:
                    pass

            total_a = snap.connector.total_current
            total_w = snap.connector.total_power
            voltages = [p.voltage for p in snap.connector.pins if p.voltage > 0]
            avg_v = sum(voltages) / len(voltages) if voltages else 0
            summary = self.query_one("#summary", Static)
            summary.update(
                f"Total: {total_a:.2f} A  {total_w:.1f} W  |  Avg Voltage: {avg_v:.3f} V"
            )

        if snap.gpu:
            g = snap.gpu
            gpu_text = (
                f"GPU: {g.power_draw:.0f}/{g.power_limit:.0f}W  "
                f"{g.temperature}C  Fan {g.fan_speed}%  "
                f"{g.clock_graphics}MHz/{g.clock_memory}MHz  "
                f"Util {g.util_gpu}%  VRAM {g.vram_used}/{g.vram_total}MB"
            )
            self.query_one("#gpu-stats", Static).update(gpu_text)

        if snap.alerts:
            log = self.query_one("#alert-log", RichLog)
            from datetime import datetime
            ts = datetime.fromtimestamp(snap.timestamp).strftime("%H:%M:%S")
            for alert in snap.alerts:
                color = "red" if alert.startswith("ALERT") else "yellow"
                log.write(f"[{color}][{ts}] {alert}[/{color}]")

    def action_clear_log(self) -> None:
        self.query_one("#alert-log", RichLog).clear()


def run_tui(bus=None, address=None, register=None):
    app = GpuPowerMonitorApp(bus=bus, address=address, register=register)
    app.run()
