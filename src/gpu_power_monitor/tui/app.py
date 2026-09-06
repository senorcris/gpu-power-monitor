import logging
import os
import signal
import re
import queue
import subprocess
import threading
import time as time_mod
from collections import deque
from dataclasses import dataclass, field
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.widgets import (
    DataTable, Footer, Header, RichLog, Static, TabbedContent, TabPane,
)
from textual import work
from textual_plotext import PlotextPlot

from ..config import (
    GRAPH_HISTORY_LENGTH, I2C_BUS, I2C_ADDRESS, I2C_REGISTER,
    REFRESH_INTERVAL, REFRESH_RATE, NUM_PINS, get_socket_path, get_gpu_profile,
)
from ..protocol import MonitorSnapshot
from .widgets import PinGauge, PowerLimitModal, StressTestModal, DetailsModal, TemperaturePanel, MetricPanel, _STRESS_PRESETS

logger = logging.getLogger(__name__)

THROTTLE_REASONS = {
    0x0000000000000001: "GpuIdle",
    0x0000000000000002: "AppClkSetting",
    0x0000000000000004: "SwPowerCap",
    0x0000000000000008: "HwSlowdown",
    0x0000000000000010: "SyncBoost",
    0x0000000000000020: "SwThermalSlowdown",
    0x0000000000000040: "HwThermalSlowdown",
    0x0000000000000080: "HwPowerBrakeSlowdown",
}


def _decode_throttle_reasons(bitmask: int) -> list[str]:
    """Decode NVML throttle reasons bitmask into human-readable labels."""
    reasons = []
    for bit, name in THROTTLE_REASONS.items():
        if bitmask & bit:
            reasons.append(name)
    return reasons


@dataclass
class _StressInfo:
    start_time: float
    duration: int
    label: str
    popen: object = None  # subprocess.Popen, used to reap zombies
    state: str = "Running"
    output: queue.SimpleQueue = field(default_factory=queue.SimpleQueue)
    tail: deque = field(default_factory=lambda: deque(maxlen=8))
    output_done: threading.Event | None = None
    stopping: bool = False


def _alert_key(message: str) -> str:
    """Stable condition identity, independent of measured values and severity."""
    match = re.search(r"Pin \d+ (?:current|voltage)|GPU (?:temperature|power)|Connector power", message)
    return match.group() if match else message.split(": ", 1)[-1]


class ProcessPane(TabPane):
    """A docked process list must not activate its hidden tab on focus."""

    def on_tab_pane_focused(self, event: TabPane.Focused) -> None:
        if self.styles.dock == "left":
            event.stop()


class GpuPowerMonitorApp(App):
    """TUI for monitoring GPU 12V-2x6 connector power delivery."""

    TITLE = "GPU Power Monitor"

    def get_driver_class(self):
        driver_class = super().get_driver_class()
        if os.name == "posix":
            from textual.drivers.linux_driver import LinuxDriver
            from .driver import CleanExitLinuxDriver

            if driver_class is LinuxDriver:
                return CleanExitLinuxDriver
        return driver_class

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("m", "show_monitor", "Monitor", show=False),
        Binding("x", "show_processes", "Processes"),
        Binding("e", "show_events", "History", show=False),
        Binding("g", "cycle_graph", "Graph"),
        Binding("a", "conditions", "Alerts"),
        Binding("r", "clear_log", "Clear history", show=False),
        Binding("s", "stress_test", "Stress"),
        Binding("p", "power_limit", "Power"),
        Binding("k", "kill_process", "Terminate", show=False),
    ]

    DEFAULT_CSS = """
    Screen { layout: vertical; }
    #health-status { height: 2; padding: 0 1; background: $surface; text-style: bold; }
    #source-status { height: 1; padding: 0 1; color: $text-muted; }
    #stress-status { height: 1; padding: 0 1; display: none; }
    #views { height: 1fr; }
    TabPane { padding: 0; height: 1fr; }
    #monitor-scroll { height: 1fr; }
    #pin-row { height: auto; width: 100%; display: none;
        grid-size: 6; grid-columns: 1fr; grid-rows: 7; }
    #summary { height: auto; padding: 0 1; color: $text-muted; }
    #gpu-stats { height: auto; padding: 0 1; color: $text-muted; }
    #metric-grid { height: auto; grid-size: 3; grid-columns: 1fr;
        grid-rows: 5; grid-gutter: 0 1; }
    #recovery { height: auto; max-height: 2; color: $warning; display: none; }
    #graph-hint, #latest-event, .page-hint { height: 1; color: $text-muted; }
    #power-graph, #vram-graph, #temp-graph { height: 8; }
    #alert-log, #process-table { height: 1fr; border: round $accent; }
    #kill-confirm { height: 2; background: $warning; color: $text; display: none; }
    """

    def __init__(self, bus=None, address=None, register=None, **kwargs):
        super().__init__(**kwargs)
        self._i2c_bus = bus if bus is not None else I2C_BUS
        self._i2c_address = address if address is not None else I2C_ADDRESS
        self._i2c_register = register if register is not None else I2C_REGISTER
        self._power_history: deque[float] = deque(maxlen=GRAPH_HISTORY_LENGTH)
        self._vram_history: deque[float] = deque(maxlen=GRAPH_HISTORY_LENGTH)
        self._temp_history: deque[float] = deque(maxlen=GRAPH_HISTORY_LENGTH)
        self._thermal_profile: dict | None = None
        self._power_profile: dict | None = None
        self._kill_confirm_pid: int | None = None
        self._stress_tests: dict[int, _StressInfo] = {}  # pid -> info
        self._last_processes: list = []  # latest snapshot's process list
        self._last_alerts: dict[str, str] = {}
        self._connector_visible = False  # pin row hidden until connector data arrives
        self._gpu_monitor = None  # GpuMonitor reference for power limit control
        self._control_monitor = None  # UI-owned NVML connection when using the daemon
        self._last_snapshot: MonitorSnapshot | None = None
        self._last_good: dict[str, float] = {}
        self._graph_index = 0
        self._latest_event = "No events yet. Active conditions remain above; e opens history."
        self._stale = False
        self._kill_confirm_name = ""
        self._source_text = "Source: connecting | No samples yet"
        self._wide_processes = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("WAITING · Connecting to GPU and connector…", id="health-status", markup=False)
        yield Static("Source: connecting | No samples yet", id="source-status", markup=False)
        yield Static("", id="stress-status", markup=False)
        with TabbedContent(id="views"):
            with TabPane("Monitor (m)", id="monitor"):
                with VerticalScroll(id="monitor-scroll"):
                    yield Static("", id="recovery", markup=False)
                    with Grid(id="pin-row"):
                        for i in range(1, NUM_PINS + 1):
                            yield PinGauge(pin_number=i, id=f"pin-{i}")
                    yield Static("Connector: waiting for readings", id="summary", markup=False)
                    yield Static("GPU: waiting for readings", id="gpu-stats", markup=False)
                    with Grid(id="metric-grid"):
                        yield TemperaturePanel(id="temperature")
                        yield MetricPanel("GPU power", id="metric-power")
                        yield MetricPanel("Fan speed", id="metric-fan")
                        yield MetricPanel("GPU activity", id="metric-activity")
                        yield MetricPanel("VRAM", id="metric-vram")
                        yield MetricPanel("Clock speeds", id="metric-clocks")
                    yield Static("g: switch graph · a: active conditions and connection details", id="graph-hint", markup=False)
                    yield PlotextPlot(id="power-graph")
                    yield PlotextPlot(id="vram-graph")
                    yield PlotextPlot(id="temp-graph")
                    yield Static(self._latest_event, id="latest-event", markup=False)
            with ProcessPane("Processes (x)", id="processes"):
                yield DataTable(id="process-table", cursor_type="row")
                yield Static("↑/↓ select · k: confirm termination", classes="page-hint", markup=False)
            with TabPane("Event history (e)", id="events"):
                yield Static("History only · r clears history · a shows current conditions", classes="page-hint", markup=False)
                yield RichLog(id="alert-log", markup=True, wrap=True)
        yield Static("", id="kill-confirm", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self._ui("#process-table", DataTable)
        table.add_column("PID", width=7, key="pid")
        table.add_column("Name", width=max(20, self.size.width - 33), key="name")
        table.add_column("VRAM (MB)", width=9, key="vram")
        table.add_column("GPU %", width=5, key="util")
        table.border_title = "GPU Processes"
        self._ui("#alert-log", RichLog).border_title = "Event history"
        self.set_interval(REFRESH_INTERVAL, self._tick)
        self._layout()
        self._start_reader()

    def _ui(self, selector, widget_type=None):
        """Update the dashboard even while a control modal is open."""
        return self.screen_stack[0].query_one(selector, widget_type)

    def _layout(self) -> None:
        if not self.is_running:
            return
        wide = self.size.width >= 140
        views = self._ui("#views", TabbedContent)
        pane = self._ui("#processes")
        if wide != self._wide_processes:
            self._cancel_kill()
            self._wide_processes = wide
            if wide:
                if views.active == "processes":
                    views.active = "monitor"
                views.hide_tab("processes")
            else:
                views.show_tab("processes")
                if self._ui("#process-table").has_focus:
                    views.active = "processes"
        pane.styles.dock = "left" if wide else "none"
        pane.styles.width = 40 if wide else "100%"
        pane.styles.margin = (0, 2, 0, 0) if wide else (0, 0, 0, 0)
        pane.display = wide or views.active == "processes"
        snap = self._last_snapshot
        pins = bool(snap and snap.connector and not self._stale)
        pin_grid = self._ui("#pin-row")
        pin_grid.display = pins
        # Reserve room for the scroll bar; keep labels and readings unwrapped.
        width = max(1, self.size.width - (42 if wide else 0) - 2)
        columns = 6 if width >= 108 else 3 if width >= 60 else 2 if width >= 32 else 1
        pin_grid.styles.grid_size_columns = columns
        pin_grid.styles.grid_size_rows = (NUM_PINS + columns - 1) // columns
        metric_columns = 3 if width >= 92 else 2 if width >= 61 else 1
        metric_grid = self._ui("#metric-grid")
        metric_grid.styles.grid_size_columns = metric_columns
        metric_grid.styles.grid_size_rows = 6 // metric_columns
        gpu = bool(snap and snap.gpu and not self._stale)
        for name in ("power", "vram", "temp"):
            widget = self._ui(f"#{name}-graph")
            widget.display = gpu
        self._ui("#graph-hint", Static).update("Scroll for graphs · g: next graph · a: details")
        table = self._ui("#process-table", DataTable)
        if table.columns:
            table.cell_padding = 0 if wide else 1
            table.columns["pid"].width = 8 if wide else 7
            table.columns["name"].width = 14 if wide else max(20, self.size.width - 33)
            table.refresh(layout=True)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        if event.tabbed_content.id == "views":
            self._cancel_kill()
            self._layout()

    def on_resize(self) -> None:
        if self.is_running and self.screen_stack and list(self.screen_stack[0].query("#views")):
            self._layout()

    def action_show_monitor(self):
        self._ui("#views", TabbedContent).active = "monitor"

    def action_show_processes(self):
        self._ui("#views", TabbedContent).active = "monitor" if self._wide_processes else "processes"
        self._ui("#process-table", DataTable).focus()

    def action_show_events(self):
        self._ui("#views", TabbedContent).active = "events"
        self._ui("#alert-log", RichLog).focus()

    def action_cycle_graph(self):
        self._graph_index = (self._graph_index + 1) % 3
        self.action_show_monitor()
        name = ("power", "vram", "temp")[self._graph_index]
        self._ui(f"#{name}-graph").scroll_visible(animate=False, top=True)

    def _log_event(self, message: str) -> None:
        self._latest_event = message
        if self.is_running:
            stamp = time_mod.strftime("%H:%M:%S")
            self._ui("#alert-log", RichLog).write(Text(f"{stamp} {message}"))
            self._ui("#latest-event", Static).update(f"Latest: {message}")

    def _tick(self) -> None:
        self._poll_stress()
        snap = self._last_snapshot
        if snap and time_mod.time() - snap.timestamp > 5 and not self._stale:
            self._stale = True
            self._power_history.clear()
            self._vram_history.clear()
            self._temp_history.clear()
            self._ui("#summary", Static).update("Connector readings stale — waiting for fresh data")
            self._ui("#gpu-stats", Static).update("GPU readings stale — waiting for fresh data")
            self._ui("#temperature", TemperaturePanel).clear_reading("Stale · waiting for fresh data")
            self._clear_metrics("Stale · awaiting readings")
            self._layout()
        self._update_status()

    def _update_status(self):
        snap = self._last_snapshot
        if not snap:
            return
        age = lambda key: (f"{max(0, time_mod.time() - self._last_good[key]):.0f}s ago"
                           if key in self._last_good else "never")
        source = "Daemon" if snap.source == "daemon" else f"Direct (I2C {self._i2c_bus}, NVML)"
        self._source_text = f"{source} | Last good: pins {age('connector')}, GPU {age('gpu')}"
        self._ui("#source-status", Static).update(self._source_text)
        missing = []
        if snap.connector is None:
            missing.append("connector")
        if snap.gpu is None:
            missing.append("GPU")
        alerts = sorted(self._last_alerts.values(), key=lambda a: not a.startswith("ALERT"))
        critical = sum(a.startswith("ALERT") for a in alerts)
        if self._stale:
            headline = "STALE · No fresh samples · a: connection details"
        elif missing:
            headline = f"UNAVAILABLE · {', '.join(missing)} · retrying · a: details"
        elif critical:
            headline = f"ALERT · {critical} critical / {len(alerts)-critical} warnings · a: all conditions"
        elif alerts:
            headline = f"WARN · {len(alerts)} active warnings · a: all conditions"
        else:
            headline = "NORMAL · No active warnings"
        detail = alerts[0] if alerts else "All reported readings are within configured thresholds."
        if (missing or self._stale) and alerts:
            detail = "Last known: " + detail
        elif missing or self._stale:
            detail = "Health cannot be confirmed until readings return."
        if not alerts and snap.connector and not self._stale:
            pin = max(snap.connector.pins, key=lambda p: p.current, default=None)
            if pin:
                detail += f" Highest: Pin {pin.pin} {pin.current:.2f}A."
        color = "red" if critical else "yellow" if alerts or missing or self._stale else "green"
        self._ui("#health-status", Static).update(Text(headline + "\n" + detail, style=color))
        reasons = [f"{key}: {value}" for key, value in snap.errors.items()]
        recovery = self._ui("#recovery", Static)
        recovery.display = bool(missing or self._stale)
        recovery.update("; ".join(reasons) if reasons else "Waiting for readings. Check I2C permissions / NVIDIA driver. Press a for details.")

    def action_conditions(self):
        snap = self._last_snapshot
        status = "Last known conditions (readings incomplete/stale)" if (
            self._stale or not snap or snap.connector is None or snap.gpu is None
        ) else "Active conditions"
        lines = [status, "", *self._last_alerts.values()]
        if not self._last_alerts:
            lines.append("No reported warnings." if snap and snap.gpu else "Waiting for sensor readings.")
        lines += ["", "Connection and recovery", self._source_text]
        if snap:
            lines.extend(f"{key}: {value}" for key, value in snap.errors.items())
        lines += ["Polling retries automatically. If the daemon stalls, direct reads take over.",
                  f"Connector: check /dev/i2c-{self._i2c_bus} permissions and the selected bus.",
                  "GPU: check NVIDIA driver availability with nvidia-smi.", "", "Thresholds",
                  "Pin current: WARN 7.5A / ALERT 9.2A; voltage: 10–13V."]
        if self._thermal_profile:
            lines.append(f"GPU temperature: WARN {self._thermal_profile['temp_warn']}C / ALERT {self._thermal_profile['temp_alarm']}C.")
        if self._power_profile:
            lines.append(f"GPU power: WARN {self._power_profile['power_warn_watts']}W / ALERT {self._power_profile['power_alarm_watts']}W.")
        self.push_screen(DetailsModal("\n".join(lines)))

    @work(exclusive=True, thread=True)
    def _start_reader(self) -> None:
        """Background thread: try daemon socket, fall back to direct reads."""
        import time
        from textual.worker import get_current_worker, NoActiveWorker

        try:
            worker = get_current_worker()
        except NoActiveWorker:
            worker = None

        socket_path = get_socket_path()

        # Try daemon socket first
        s = None
        try:
            import socket as sock_mod
            s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(socket_path)
            logger.info("Connected to daemon socket")
            buf = b""
            try:
                while worker is None or not worker.is_cancelled:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line:
                            try:
                                snap = MonitorSnapshot.from_json(line.decode())
                                snap.source = "daemon"
                                self.call_from_thread(self._apply_snapshot, snap)
                            except Exception as e:
                                logger.debug(f"Bad snapshot: {e}")
            finally:
                s.close()
        except (OSError, ConnectionRefusedError, FileNotFoundError):
            if s is not None:
                s.close()
            logger.info("Daemon not available, falling back to direct reads")

        if worker is not None and worker.is_cancelled:
            return

        # Direct polling fallback
        from ..i2c import IT8915Reader
        from ..gpu import GpuMonitor
        from ..daemon import _read_snapshot

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
        self._gpu_monitor = gpu_mon

        try:
            while worker is None or not worker.is_cancelled:
                snap = _read_snapshot(i2c_reader, gpu_mon)
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
            logger.exception("Could not display snapshot")

    def _render_graph(
        self, widget_id: str, history: deque, title: str, ylabel: str,
        ylim_max: float | None = None,
        thresholds: list[tuple[float, str]] | None = None,
        show_xlabel: bool = True,
    ) -> None:
        """Render a PlotextPlot with a fixed time-based X axis (seconds ago)."""
        plot_widget = self._ui(widget_id, PlotextPlot)
        p = plot_widget.plt
        p.clear_data()
        p.clear_figure()

        # Build X axis: newest point at 0, older points negative
        max_seconds = GRAPH_HISTORY_LENGTH / REFRESH_RATE
        n = len(history)
        x = [-(n - 1 - i) / REFRESH_RATE for i in range(n)]

        # Determine line color from thresholds
        color = None
        if thresholds and n > 0:
            current = history[-1]
            sorted_thresh = sorted(thresholds, key=lambda t: t[0])
            if current >= sorted_thresh[-1][0]:
                color = "red"
            elif current >= sorted_thresh[0][0]:
                color = "yellow"
            else:
                color = "green"

        if color:
            p.plot(x, list(history), marker="braille", color=color)
        else:
            p.plot(x, list(history), marker="braille")

        p.xlim(-max_seconds, 0)
        if ylim_max is not None:
            ceiling = max(ylim_max, max(history, default=0), max((v for v, _ in thresholds or []), default=0))
            p.ylim(0, ceiling * 1.05 if thresholds else max(1, ceiling))
        p.yfrequency(5)

        # Draw threshold lines
        if thresholds:
            for value, tcolor in thresholds:
                p.hline(value, color=tcolor)

        # Build xlabel with min/avg/max stats
        if n >= 2:
            min_val = min(history)
            max_val = max(history)
            avg_val = sum(history) / n
            stats = f"min {min_val:.0f}  avg {avg_val:.0f}  max {max_val:.0f}"
            if show_xlabel:
                p.xlabel(f"{stats}  (seconds ago)")
            else:
                p.xlabel(stats)
        elif show_xlabel:
            p.xlabel("seconds ago")

        p.title(title)
        p.ylabel(ylabel)
        plot_widget.refresh()

    def _clear_metrics(self, message: str) -> None:
        for panel in self.screen_stack[0].query(MetricPanel):
            panel.clear_reading(message)

    def _update_metrics(self, g) -> None:
        profile = self._power_profile or get_gpu_profile(g.name)[0]
        color, status = ("#ff7b86", "Alert") if g.power_draw >= profile["power_alarm_watts"] else (
            ("#f5c26b", "Warning") if g.power_draw >= profile["power_warn_watts"] else
            ("#5ed6a0", "Normal")
        )
        self._ui("#metric-power", MetricPanel).update_reading(
            f"{g.power_draw:.0f} W", status,
            f"Limit {g.power_limit:.0f} W" if g.power_limit > 0 else "Power limit unavailable",
            g.power_draw / g.power_limit if g.power_limit > 0 else None, color,
        )
        self._ui("#metric-fan", MetricPanel).update_reading(
            f"{g.fan_speed}%", "Spinning" if g.fan_speed else "Stopped",
            "Reported fan speed", g.fan_speed / 100, "#78c9ed",
        )
        self._ui("#metric-activity", MetricPanel).update_reading(
            f"{g.util_gpu}%", "Active" if g.util_gpu else "Idle",
            f"Memory activity {g.util_memory}%", g.util_gpu / 100, "#78c9ed",
        )
        total, used = g.vram_total / 1024, g.vram_used / 1024
        self._ui("#metric-vram", MetricPanel).update_reading(
            f"{used:.1f} GiB", "Used",
            f"{max(0, total - used):.1f} free / {total:.1f} GiB" if total > 0 else "VRAM capacity unavailable",
            used / total if total > 0 else None, "#b7a3ee",
        )
        self._ui("#metric-clocks", MetricPanel).update_reading(
            f"{g.clock_graphics:,} MHz", "Core", "Current clock speeds", None,
            "#b7a3ee", secondary=f"{g.clock_memory:,} MHz memory",
        )

    def _apply_snapshot_inner(self, snap: MonitorSnapshot) -> None:
        self._last_snapshot = snap
        self._stale = False
        if snap.connector:
            self._last_good["connector"] = snap.timestamp
        if snap.gpu:
            self._last_good["gpu"] = snap.timestamp
        if snap.connector:
            if not self._connector_visible:
                self._connector_visible = True
                self._ui("#pin-row").styles.display = "block"
                self._ui("#summary").styles.display = "block"
            for pin in snap.connector.pins:
                try:
                    gauge = self._ui(f"#pin-{pin.pin}", PinGauge)
                    gauge.update_reading(pin)
                except Exception:
                    pass

            total_a = snap.connector.total_current
            total_w = snap.connector.total_power
            voltages = [p.voltage for p in snap.connector.pins if p.voltage > 0]
            avg_v = sum(voltages) / len(voltages) if voltages else 0
            self._ui("#summary", Static).update(
                f"Connector: {total_a:.2f} A  {total_w:.1f} W  |  Avg voltage: {avg_v:.2f} V"
            )
        else:
            self._connector_visible = False
            self._ui("#pin-row").styles.display = "none"
            self._ui("#summary", Static).update("Connector readings unavailable")

        if snap.gpu:
            for widget_id in ("#power-graph", "#vram-graph", "#temp-graph"):
                self._ui(widget_id).styles.display = "block"
            g = snap.gpu
            if g.name:
                self.sub_title = g.name
                if self._thermal_profile is None:
                    _, self._thermal_profile = get_gpu_profile(g.name)
                if self._power_profile is None:
                    self._power_profile, _ = get_gpu_profile(g.name)
            # Build throttle indicator
            throttle_str = ""
            if g.throttle_reasons:
                reasons = _decode_throttle_reasons(g.throttle_reasons)
                active = [r for r in reasons if r != "GpuIdle"]
                if active:
                    short = []
                    for r in active:
                        if "Thermal" in r:
                            short.append("Thermal")
                        elif "Power" in r or "PowerBrake" in r:
                            short.append("Power")
                        elif r == "HwSlowdown":
                            short.append("HW")
                        else:
                            short.append(r)
                    throttle_str = f"  THROTTLE: {','.join(dict.fromkeys(short))}"

            self._ui("#gpu-stats", Static).update(
                Text(throttle_str.strip(), style="bold #f5c26b") if throttle_str else ""
            )
            self._update_metrics(g)
            self._ui("#temperature", TemperaturePanel).update_reading(
                g.temperature, self._thermal_profile or get_gpu_profile(g.name)[1],
            )

            # Feed line graphs
            self._power_history.append(g.power_draw)
            self._vram_history.append(g.vram_used / 1024.0)
            self._temp_history.append(float(g.temperature))

            self._render_graph(
                "#power-graph", self._power_history,
                f"Power: {g.power_draw:.0f}W", "W",
                ylim_max=g.power_limit,
                thresholds=[(self._power_profile["power_warn_watts"], "yellow"),
                            (self._power_profile["power_alarm_watts"], "red")] if self._power_profile else None,
            )
            vram_gb = g.vram_used / 1024.0
            vram_total_gb = g.vram_total / 1024.0
            self._render_graph(
                "#vram-graph", self._vram_history,
                f"VRAM: {vram_gb:.1f}/{vram_total_gb:.0f}GB", "GB",
                ylim_max=vram_total_gb if g.vram_total else None,
                show_xlabel=False,
            )
            temp_title = f"Temp: {g.temperature}C"
            temp_ylim = 100.0
            temp_thresholds = None
            if self._thermal_profile:
                temp_ylim = float(self._thermal_profile["max_temp_spec"])
                temp_thresholds = [
                    (self._thermal_profile["temp_warn"], "yellow"),
                    (self._thermal_profile["temp_alarm"], "red"),
                ]
            self._render_graph(
                "#temp-graph", self._temp_history, temp_title, "C",
                ylim_max=temp_ylim,
                thresholds=temp_thresholds,
                show_xlabel=False,
            )

        else:
            self._ui("#gpu-stats", Static).update("GPU readings unavailable")
            self._ui("#temperature", TemperaturePanel).clear_reading("GPU readings unavailable")
            self._clear_metrics("GPU readings unavailable")
            # Discard history across a gap so old samples aren't shown as current.
            self._power_history.clear()
            self._vram_history.clear()
            self._temp_history.clear()
            for widget_id in ("#power-graph", "#vram-graph", "#temp-graph"):
                self._ui(widget_id).styles.display = "none"

        # Update process table — merge nvml/nvidia-smi data with tracked stress tests
        # Empty snapshots also replace old rows; tracked stress tests stay below.
        self._last_processes = snap.processes

        table = self._ui("#process-table", DataTable)
        now = time_mod.time()
        seen_pids: set[int] = set()

        # Build rows: list of (pid_str, name, vram_str, util_str)
        rows: list[tuple[str, str, str, str]] = []

        # Tracked stress tests first (always show, never flicker)
        self._poll_stress()
        dead_pids = []
        for pid, info in self._stress_tests.items():
            # poll() reaps zombies; returns None if still running
            if info.popen is None:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    dead_pids.append(pid)
                    continue
            seen_pids.add(pid)
            remaining = max(0, info.duration - (now - info.start_time))
            mins, secs = divmod(int(remaining), 60)
            name = f"{info.label}: {info.state} ({mins}:{secs:02d})"
            # Try to get VRAM from cached process data
            vram_str = "--"
            for proc in self._last_processes:
                if proc.pid == pid:
                    vram_str = str(proc.vram_used)
                    break
            rows.append((str(pid), name, vram_str.rjust(7), "--".rjust(5)))
        for pid in dead_pids:
            del self._stress_tests[pid]

        # Other GPU processes from cached data
        for proc in self._last_processes:
            if proc.pid in seen_pids:
                continue
            seen_pids.add(proc.pid)
            util_str = f"{proc.gpu_util}%".rjust(5) if proc.gpu_util is not None else "--".rjust(5)
            rows.append((str(proc.pid), proc.name, str(proc.vram_used).rjust(7), util_str))

        # Rebuild table only if content changed
        new_keys = [r[0] for r in rows]
        old_keys = [str(k.value) for k in table.rows]
        needs_rebuild = new_keys != old_keys

        if needs_rebuild:
            selected = None
            if table.row_count and table.cursor_row < table.row_count:
                selected = table.get_row_at(table.cursor_row)[0]
            table.clear()
            if rows:
                for pid_str, name, vram_str, util_str in rows:
                    table.add_row(pid_str, name, vram_str, util_str, key=pid_str)
                if selected in new_keys:
                    table.move_cursor(row=new_keys.index(selected))
            else:
                table.add_row("--", "No GPU processes", "--".rjust(7), "--".rjust(5))
            if self._kill_confirm_pid is not None and str(self._kill_confirm_pid) not in new_keys:
                self._cancel_kill()
        else:
            # Update cell values in place (no flicker)
            for idx, (pid_str, name, vram_str, util_str) in enumerate(rows):
                row_key = table.ordered_rows[idx].key
                for col_idx, val in enumerate([pid_str, name, vram_str, util_str]):
                    col_key = table.ordered_columns[col_idx].key
                    table.update_cell(row_key, col_key, val)

        current_alerts = {_alert_key(a): a for a in snap.alerts}
        for key, old in self._last_alerts.items():
            # An unreadable sensor cannot prove that its previous fault resolved.
            unknown = ((key.startswith("Pin ") and snap.connector is None)
                       or (key.startswith("GPU ") and snap.gpu is None)
                       or (key == "Connector power" and (snap.gpu is None or snap.connector is None)))
            if unknown:
                current_alerts.setdefault(key, old)
            elif key not in current_alerts:
                self._log_event(f"RESOLVED: {key}")
        for key, alert in current_alerts.items():
            old = self._last_alerts.get(key)
            if old is None or old.split(":", 1)[0] != alert.split(":", 1)[0]:
                self._log_event(alert)
        self._last_alerts = current_alerts
        self._update_status()
        self._layout()

    def action_clear_log(self) -> None:
        self._ui("#alert-log", RichLog).clear()
        self._ui("#latest-event", Static).update("History cleared. Active conditions are still shown above [a].")

    def action_stress_test(self) -> None:
        def on_dismiss(result: tuple[object, str] | None) -> None:
            if result is not None:
                popen, preset_key = result
                preset = _STRESS_PRESETS[preset_key]
                info = _StressInfo(
                    start_time=time_mod.time(),
                    duration=preset["duration"],
                    label=preset["label"],
                    popen=popen,
                    state="Starting",
                    output_done=threading.Event(),
                )
                self._stress_tests[popen.pid] = info

                def read_output():
                    try:
                        if popen.stdout is not None:
                            for line in popen.stdout:
                                info.output.put(line.strip())
                    finally:
                        if popen.stdout is not None:
                            popen.stdout.close()
                        info.output_done.set()

                threading.Thread(target=read_output, daemon=True).start()
                self._stress_message(f"Starting {preset['label']} (PID {popen.pid})…")
        self.push_screen(StressTestModal(), callback=on_dismiss)

    def _stress_message(self, message: str):
        self._log_event(message)
        if self.is_running:
            widget = self._ui("#stress-status", Static)
            widget.display = True
            widget.update(message)

    def _poll_stress(self):
        for pid, info in list(self._stress_tests.items()):
            while True:
                try:
                    line = info.output.get_nowait()
                except queue.Empty:
                    break
                if line == "GPU_POWER_MONITOR_RUNNING":
                    info.state = "Running"
                    info.start_time = time_mod.time()
                    self._stress_message(f"Running {info.label} (PID {pid}) · x then k to stop")
                elif line:
                    info.tail.append(line)
            code = info.popen.poll() if info.popen is not None else None
            if code is None or (info.output_done is not None and not info.output_done.is_set()):
                continue
            if info.stopping:
                result = f"Stopped {info.label} (PID {pid})"
            elif code == 0:
                result = f"Completed {info.label} (PID {pid})"
            else:
                reason = info.tail[-1] if info.tail else f"process exited with code {code}"
                result = f"FAILED {info.label}: {reason}"
            self._stress_message(result)
            del self._stress_tests[pid]

    def action_power_limit(self) -> None:
        """Open the power limit configuration modal."""
        gpu_mon = self._gpu_monitor or self._control_monitor
        if gpu_mon is None:
            from ..gpu import GpuMonitor

            gpu_mon = GpuMonitor()
            try:
                gpu_mon.open()
            except Exception as e:
                gpu_mon.close()
                self.notify(f"Could not open GPU controls: {e}", severity="error")
                return
            self._control_monitor = gpu_mon

        constraints = gpu_mon.get_power_limit_constraints()
        if not constraints:
            self.notify("Could not query power limit constraints", severity="error")
            return
        # Get current enforced limit
        stats = gpu_mon.read_stats()
        current_limit = stats.power_limit if stats else constraints.default_watts

        def on_dismiss(watts: float | None) -> None:
            if watts is not None:
                success, msg = gpu_mon.set_power_limit(watts)
                if success:
                    self.notify(msg)
                    self._log_event(msg)
                else:
                    self.notify(msg, severity="error")
                    self._log_event(f"Power limit error: {msg}")

        self.push_screen(
            PowerLimitModal(constraints, current_limit),
            callback=on_dismiss,
        )

    def action_kill_process(self) -> None:
        """Terminate the selected GPU process (with named confirmation)."""
        if (self._wide_processes and not self._ui("#process-table").has_focus) or (
            not self._wide_processes and self._ui("#views", TabbedContent).active != "processes"
        ):
            self.action_show_processes()
            return
        table = self._ui("#process-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return
        try:
            pid = int(row_key.value)
        except (ValueError, TypeError):
            return
        confirm_bar = self._ui("#kill-confirm", Static)
        tracked = self._stress_tests.get(pid)
        name = tracked.label if tracked else str(table.get_row(row_key)[1])

        if self._kill_confirm_pid == pid and self._kill_confirm_name == name:
            # Second press: confirmed
            try:
                info = self._stress_tests.get(pid)
                if info and info.popen:
                    info.popen.terminate()
                    info.stopping = True
                    info.state = "Stopping"
                else:
                    os.kill(pid, signal.SIGTERM)
                self._log_event(f"Sent SIGTERM to {name} (PID {pid})")
            except ProcessLookupError:
                self._stress_tests.pop(pid, None)
                self.notify(f"PID {pid} already exited", severity="warning")
            except PermissionError:
                self.notify(f"Permission denied killing PID {pid}", severity="error")
            self._cancel_kill()
        else:
            # First press: show confirmation
            self._kill_confirm_pid = pid
            self._kill_confirm_name = name
            confirm_bar.update(f"Terminate {name} (PID {pid})?\nPress k again to send SIGTERM; any other key cancels.")
            confirm_bar.styles.display = "block"

    def _cancel_kill(self):
        self._kill_confirm_pid = None
        self._kill_confirm_name = ""
        self._ui("#kill-confirm", Static).update("")
        self._ui("#kill-confirm").display = False

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if event.data_table.id == "process-table" and self._kill_confirm_pid is not None:
            if str(event.row_key.value) != str(self._kill_confirm_pid):
                self._cancel_kill()

    def on_key(self, event) -> None:
        """Cancel kill confirmation on any key other than k."""
        if self._kill_confirm_pid is not None and event.key != "k":
            self._cancel_kill()

    def on_unmount(self) -> None:
        """Clean up stress test subprocesses on TUI exit."""
        if self._control_monitor is not None:
            self._control_monitor.close()
            self._control_monitor = None
        for pid, info in list(self._stress_tests.items()):
            try:
                if info.popen is not None:
                    info.popen.terminate()
                    info.popen.wait(timeout=3)
                else:
                    os.kill(pid, signal.SIGTERM)
            except subprocess.TimeoutExpired:
                info.popen.kill()
                info.popen.wait(timeout=3)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        self._stress_tests.clear()


def run_tui(bus=None, address=None, register=None):
    app = GpuPowerMonitorApp(bus=bus, address=address, register=register)
    app.run()
