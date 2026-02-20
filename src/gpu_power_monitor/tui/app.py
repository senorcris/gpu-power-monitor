import logging
import os
import signal
import time as time_mod
from collections import deque
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable, Footer, Header, RichLog, Static,
)
from textual import work
from textual_plotext import PlotextPlot

from ..config import (
    GRAPH_HISTORY_LENGTH, I2C_BUS, I2C_ADDRESS, I2C_REGISTER,
    REFRESH_INTERVAL, NUM_PINS, get_socket_path,
)
from ..protocol import MonitorSnapshot
from .widgets import PinGauge, StressTestModal, _STRESS_PRESETS

logger = logging.getLogger(__name__)


@dataclass
class _StressInfo:
    start_time: float
    duration: int
    label: str


class GpuPowerMonitorApp(App):
    """TUI for monitoring GPU 12V-2x6 connector power delivery."""

    TITLE = "GPU Power Monitor - 12V-2x6 Connector"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "clear_log", "Clear Log"),
        Binding("s", "stress_test", "Stress Test"),
        Binding("k", "kill_process", "Kill Process"),
    ]

    DEFAULT_CSS = """
    Screen {
        layout: vertical;
    }
    #main-layout {
        height: 1fr;
    }
    #left-panel {
        width: 1fr;
        min-width: 36;
    }
    #right-panel {
        width: 2fr;
    }
    #process-table {
        height: 1fr;
        border: solid $accent;
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
        height: 2;
        width: 100%;
        text-align: center;
        border: solid $success;
    }
    #power-graph {
        height: 8;
    }
    #vram-graph {
        height: 8;
    }
    #alert-log {
        height: 1fr;
        border: solid $accent;
    }
    #kill-confirm {
        height: 1;
        background: $warning;
        color: $text;
        text-align: center;
        display: none;
    }
    """

    def __init__(self, bus=None, address=None, register=None, **kwargs):
        super().__init__(**kwargs)
        self._i2c_bus = bus if bus is not None else I2C_BUS
        self._i2c_address = address if address is not None else I2C_ADDRESS
        self._i2c_register = register if register is not None else I2C_REGISTER
        self._power_history: deque[float] = deque(maxlen=GRAPH_HISTORY_LENGTH)
        self._vram_history: deque[float] = deque(maxlen=GRAPH_HISTORY_LENGTH)
        self._kill_confirm_pid: int | None = None
        self._stress_tests: dict[int, _StressInfo] = {}  # pid -> info
        self._last_processes: list = []  # cache last known process list

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield DataTable(id="process-table", cursor_type="row")
            with Vertical(id="right-panel"):
                with Horizontal(id="pin-row"):
                    for i in range(1, NUM_PINS + 1):
                        yield PinGauge(pin_number=i, id=f"pin-{i}")
                yield Static("Total: -- A  -- W  |  Avg Voltage: -- V", id="summary")
                yield Static("GPU: --", id="gpu-stats")
                yield PlotextPlot(id="power-graph")
                yield PlotextPlot(id="vram-graph")
                yield RichLog(id="alert-log", markup=True, wrap=True)
        yield Static("", id="kill-confirm")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#process-table", DataTable)
        table.add_columns("PID", "Name", "VRAM (MB)", "GPU %")
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

                try:
                    processes = gpu_mon.get_processes()
                except Exception:
                    processes = []

                snap = MonitorSnapshot(connector=connector, gpu=gpu, processes=processes)
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
        try:
            self._apply_snapshot_inner(snap)
        except Exception:
            # Guard against NoMatches during screen transitions
            pass

    def _apply_snapshot_inner(self, snap: MonitorSnapshot) -> None:
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
            self.query_one("#summary", Static).update(
                f"Total: {total_a:.2f} A  {total_w:.1f} W  |  Avg Voltage: {avg_v:.3f} V"
            )

        if snap.gpu:
            g = snap.gpu
            if g.name:
                self.sub_title = g.name
            vram_pct = round(g.vram_used / g.vram_total * 100) if g.vram_total else 0
            gpu_text = (
                f"Power {g.power_draw:.0f}/{g.power_limit:.0f}W  |  "
                f"Temp {g.temperature}C  Fan {g.fan_speed}%  |  "
                f"GPU {g.util_gpu}%  Mem {g.util_memory}%\n"
                f"Core {g.clock_graphics}MHz  Mem {g.clock_memory}MHz  |  "
                f"VRAM {g.vram_used}/{g.vram_total}MB ({vram_pct}%)"
            )
            self.query_one("#gpu-stats", Static).update(gpu_text)

            # Feed line graphs
            self._power_history.append(g.power_draw)
            power_plot = self.query_one("#power-graph", PlotextPlot)
            plt = power_plot.plt
            plt.clear_data()
            plt.clear_figure()
            plt.plot(list(self._power_history), marker="braille")
            plt.title(f"Power: {g.power_draw:.0f}W")
            plt.ylabel("W")
            power_plot.refresh()

            self._vram_history.append(float(g.vram_used))
            vram_plot = self.query_one("#vram-graph", PlotextPlot)
            plt2 = vram_plot.plt
            plt2.clear_data()
            plt2.clear_figure()
            plt2.plot(list(self._vram_history), marker="braille")
            plt2.title(f"VRAM: {g.vram_used} / {g.vram_total} MB")
            plt2.ylabel("MB")
            vram_plot.refresh()

        # Update process table — merge nvml/nvidia-smi data with tracked stress tests
        # Cache non-empty process lists so we don't flicker when nvidia-smi is slow
        if snap.processes:
            self._last_processes = snap.processes

        table = self.query_one("#process-table", DataTable)
        now = time_mod.time()
        seen_pids: set[int] = set()

        # Build rows: list of (pid_str, name, vram_str, util_str)
        rows: list[tuple[str, str, str, str]] = []

        # Tracked stress tests first (always show, never flicker)
        dead_pids = []
        for pid, info in self._stress_tests.items():
            try:
                os.kill(pid, 0)  # check if alive
            except ProcessLookupError:
                dead_pids.append(pid)
                continue
            seen_pids.add(pid)
            remaining = max(0, info.duration - (now - info.start_time))
            mins, secs = divmod(int(remaining), 60)
            name = f"{info.label} ({mins}:{secs:02d})"
            # Try to get VRAM from cached process data
            vram_str = "--"
            for proc in self._last_processes:
                if proc.pid == pid:
                    vram_str = str(proc.vram_used)
                    break
            rows.append((str(pid), name, vram_str, "--"))
        for pid in dead_pids:
            del self._stress_tests[pid]

        # Other GPU processes from cached data
        for proc in self._last_processes:
            if proc.pid in seen_pids:
                continue
            seen_pids.add(proc.pid)
            util_str = f"{proc.gpu_util}%" if proc.gpu_util is not None else "--"
            rows.append((str(proc.pid), proc.name, str(proc.vram_used), util_str))

        # Rebuild table only if content changed
        new_keys = [r[0] for r in rows]
        old_keys = [str(k.value) for k in table.rows]
        needs_rebuild = new_keys != old_keys

        if needs_rebuild:
            table.clear()
            if rows:
                for pid_str, name, vram_str, util_str in rows:
                    table.add_row(pid_str, name, vram_str, util_str, key=pid_str)
            else:
                table.add_row("--", "No GPU processes", "--", "--")
        else:
            # Update cell values in place (no flicker)
            for idx, (pid_str, name, vram_str, util_str) in enumerate(rows):
                row_key = table.ordered_rows[idx].key
                for col_idx, val in enumerate([pid_str, name, vram_str, util_str]):
                    col_key = table.ordered_columns[col_idx].key
                    table.update_cell(row_key, col_key, val)

        if snap.alerts:
            log = self.query_one("#alert-log", RichLog)
            from datetime import datetime
            ts = datetime.fromtimestamp(snap.timestamp).strftime("%H:%M:%S")
            for alert in snap.alerts:
                color = "red" if alert.startswith("ALERT") else "yellow"
                log.write(f"[{color}][{ts}] {alert}[/{color}]")

    def action_clear_log(self) -> None:
        self.query_one("#alert-log", RichLog).clear()

    def action_stress_test(self) -> None:
        def on_dismiss(result: tuple[int, str] | None) -> None:
            if result is not None:
                pid, preset_key = result
                preset = _STRESS_PRESETS[preset_key]
                self._stress_tests[pid] = _StressInfo(
                    start_time=time_mod.time(),
                    duration=preset["duration"],
                    label=preset["label"],
                )
                self.notify(f"Started {preset['label']} (PID {pid})")
        self.push_screen(StressTestModal(), callback=on_dismiss)

    def action_kill_process(self) -> None:
        """Kill the selected GPU process (with confirmation)."""
        table = self.query_one("#process-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return
        try:
            pid = int(row_key.value)
        except (ValueError, TypeError):
            return
        confirm_bar = self.query_one("#kill-confirm", Static)

        if self._kill_confirm_pid == pid:
            # Second press: confirmed
            try:
                os.kill(pid, signal.SIGTERM)
                self._stress_tests.pop(pid, None)
                self.notify(f"Sent SIGTERM to PID {pid}")
            except ProcessLookupError:
                self._stress_tests.pop(pid, None)
                self.notify(f"PID {pid} already exited", severity="warning")
            except PermissionError:
                self.notify(f"Permission denied killing PID {pid}", severity="error")
            self._kill_confirm_pid = None
            confirm_bar.update("")
            confirm_bar.styles.display = "none"
        else:
            # First press: show confirmation
            self._kill_confirm_pid = pid
            confirm_bar.update(f"Kill PID {pid}? Press k again to confirm, any other key to cancel.")
            confirm_bar.styles.display = "block"

    def on_key(self, event) -> None:
        """Cancel kill confirmation on any key other than k."""
        if self._kill_confirm_pid is not None and event.key != "k":
            self._kill_confirm_pid = None
            confirm_bar = self.query_one("#kill-confirm", Static)
            confirm_bar.update("")
            confirm_bar.styles.display = "none"

    def on_unmount(self) -> None:
        """Clean up stress test subprocesses on TUI exit."""
        for pid in list(self._stress_tests):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        self._stress_tests.clear()


def run_tui(bus=None, address=None, register=None):
    app = GpuPowerMonitorApp(bus=bus, address=address, register=register)
    app.run()
