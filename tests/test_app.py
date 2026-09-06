"""Tests for TUI app logic and telemetry transitions."""
import asyncio
from unittest.mock import Mock, patch

import pytest
from textual.widgets import DataTable, Static

from gpu_power_monitor.protocol import ConnectorReading, GpuStats, MonitorSnapshot, PinReading, GpuProcess
from gpu_power_monitor.tui.app import GpuPowerMonitorApp, _decode_throttle_reasons, THROTTLE_REASONS, _StressInfo
from gpu_power_monitor.gpu import PowerLimitConstraints
from gpu_power_monitor.tui.widgets import PowerLimitModal


def test_power_limit_works_while_connected_to_daemon():
    app = GpuPowerMonitorApp()
    stats = GpuStats(name="RTX 5090", power_limit=575)
    monitor = Mock()
    monitor.get_power_limit_constraints.return_value = PowerLimitConstraints(200, 600, 575)
    monitor.read_stats.return_value = stats
    monitor.set_power_limit.return_value = (True, "Power limit set")

    class StopReader(BaseException):
        pass

    # Stop after one daemon frame without entering the direct polling fallback.
    with patch("socket.socket") as socket_cls, patch(
        "gpu_power_monitor.gpu.GpuMonitor", return_value=monitor
    ), patch.object(app, "push_screen") as push, patch.object(app, "notify"), patch.object(
        app, "query_one"
    ), patch.object(app, "call_from_thread", side_effect=lambda *args: app.action_power_limit()):
        socket_cls.return_value.recv.side_effect = [
            MonitorSnapshot(None, stats).to_json().encode(), StopReader,
        ]
        with pytest.raises(StopReader):
            GpuPowerMonitorApp._start_reader.__wrapped__(app)
        socket_cls.return_value.connect.assert_called_once()
        push.assert_called_once()
        assert isinstance(push.call_args.args[0], PowerLimitModal)
        monitor.open.assert_called_once()
        monitor.set_power_limit.assert_not_called()
        callback = push.call_args.kwargs["callback"]
        callback(None)
        monitor.set_power_limit.assert_not_called()
        callback(450)
        monitor.set_power_limit.assert_called_once_with(450)
        app.action_power_limit()
        monitor.open.assert_called_once()
        app.on_unmount()
        monitor.close.assert_called_once()


def test_power_controls_retry_after_initialization_failure():
    app = GpuPowerMonitorApp()
    monitor = Mock()
    monitor.open.side_effect = [RuntimeError("NVML unavailable"), None]
    monitor.get_power_limit_constraints.return_value = PowerLimitConstraints(200, 600, 575)
    monitor.read_stats.return_value = GpuStats(power_limit=575)
    with patch("gpu_power_monitor.gpu.GpuMonitor", return_value=monitor), patch.object(
        app, "push_screen"
    ) as push, patch.object(app, "notify") as notify:
        app.action_power_limit()
        push.assert_not_called()
        monitor.close.assert_called_once()
        assert app._control_monitor is None
        assert "NVML unavailable" in notify.call_args.args[0]
        app.action_power_limit()
        push.assert_called_once()
        assert monitor.open.call_count == 2
        app.on_unmount()
        assert monitor.close.call_count == 2


def test_power_controls_reuse_direct_monitor():
    app = GpuPowerMonitorApp()
    monitor = app._gpu_monitor = Mock()
    monitor.get_power_limit_constraints.return_value = PowerLimitConstraints(200, 600, 575)
    monitor.read_stats.return_value = GpuStats(power_limit=575)
    with patch("gpu_power_monitor.gpu.GpuMonitor") as monitor_cls, patch.object(
        app, "push_screen"
    ) as push:
        app.action_power_limit()
        push.assert_called_once()
        monitor_cls.assert_not_called()
        app.on_unmount()
        # Direct reader owns this connection and closes it in its own finally.
        monitor.close.assert_not_called()


@pytest.mark.parametrize("model,temperature,severity", [
    ("RTX 5060 Ti", 76, "WARN"),
    ("RTX 5080", 83, "ALERT"),
    ("RTX 5090", 85, "ALERT"),
])
def test_direct_reader_uses_model_thermal_thresholds(model, temperature, severity):
    app = GpuPowerMonitorApp()
    stats = GpuStats(name=model, temperature=temperature)

    class StopReader(BaseException):
        pass

    with patch("socket.socket") as socket_cls, patch(
        "gpu_power_monitor.gpu.GpuMonitor"
    ) as gpu_cls, patch("gpu_power_monitor.i2c.IT8915Reader") as i2c_cls, patch.object(
        app, "call_from_thread", side_effect=StopReader
    ) as deliver:
        socket_cls.return_value.connect.side_effect = FileNotFoundError
        gpu_cls.return_value.read_stats.return_value = stats
        gpu_cls.return_value.get_processes.return_value = []
        i2c_cls.return_value.read_pins.return_value = None
        with pytest.raises(StopReader):
            GpuPowerMonitorApp._start_reader.__wrapped__(app)
        snap = deliver.call_args.args[1]
        assert any(a.startswith(severity) and "temperature" in a for a in snap.alerts)
        from gpu_power_monitor.daemon import _build_alerts
        assert snap.alerts == _build_alerts(snap)
        i2c_cls.return_value.close.assert_called_once()
        gpu_cls.return_value.close.assert_called_once()


@pytest.mark.parametrize("tracked_stress", [False, True])
def test_empty_process_snapshot_removes_exited_process(tracked_stress):
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(160, 50)):
                if tracked_stress:
                    app._stress_tests[456] = _StressInfo(
                        start_time=0, duration=30, label="Quick Test",
                        popen=Mock(poll=Mock(return_value=None)),
                    )
                table = app.query_one("#process-table", DataTable)
                app._apply_snapshot_inner(MonitorSnapshot(
                    None, None, [GpuProcess(123, "finished-job", 100)],
                ))
                assert "123" in [key.value for key in table.rows]
                for _ in range(3):
                    app._apply_snapshot_inner(MonitorSnapshot(None, None, []))
                keys = [key.value for key in table.rows]
                assert "123" not in keys
                if tracked_stress:
                    assert keys == ["456"]
                else:
                    assert table.get_row_at(0)[1] == "No GPU processes"

    asyncio.run(check())


@pytest.mark.parametrize("lose_connector,lose_gpu", [(True, False), (False, True), (True, True)])
def test_missing_readings_and_recovery(lose_connector, lose_gpu):
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(160, 50)):
                connector = ConnectorReading([
                    PinReading(i, f"Pin {i}", 12000, 1000) for i in range(1, 7)
                ])
                gpu = GpuStats(name="RTX 5090", power_draw=72, power_limit=575, temperature=60)
                healthy = MonitorSnapshot(connector, gpu)
                app._apply_snapshot_inner(healthy)
                assert app.query_one("#pin-row").styles.display == "block"
                assert "72.0 W" in str(app.query_one("#summary", Static).render())

                missing = MonitorSnapshot(
                    None if lose_connector else connector,
                    None if lose_gpu else gpu,
                )
                for _ in range(3):
                    app._apply_snapshot_inner(missing)
                summary = str(app.query_one("#summary", Static).render())
                gpu_text = str(app.query_one("#gpu-stats", Static).render())
                assert ("unavailable" in summary) == lose_connector
                assert ("unavailable" in gpu_text) == lose_gpu
                assert app.query_one("#pin-row").styles.display == ("none" if lose_connector else "block")
                for widget_id in ("#power-graph", "#vram-graph", "#temp-graph"):
                    assert app.query_one(widget_id).styles.display == ("none" if lose_gpu else "block")
                if lose_gpu:
                    assert not app._power_history
                    assert not app._vram_history
                    assert not app._temp_history

                app._apply_snapshot_inner(healthy)
                assert app.query_one("#pin-row").styles.display == "block"
                assert "72.0 W" in str(app.query_one("#summary", Static).render())
                assert "unavailable" not in str(app.query_one("#gpu-stats", Static).render())
                for widget_id in ("#power-graph", "#vram-graph", "#temp-graph"):
                    assert app.query_one(widget_id).styles.display == "block"
                if lose_gpu:
                    assert list(app._power_history) == [72]
                    assert list(app._temp_history) == [60]

    asyncio.run(check())


class TestDecodeThrottleReasons:
    def test_no_throttle(self):
        assert _decode_throttle_reasons(0) == []

    def test_single_reason(self):
        result = _decode_throttle_reasons(0x0000000000000004)
        assert result == ["SwPowerCap"]

    def test_multiple_reasons(self):
        bitmask = 0x0000000000000008 | 0x0000000000000040  # HwSlowdown + HwThermalSlowdown
        result = _decode_throttle_reasons(bitmask)
        assert "HwSlowdown" in result
        assert "HwThermalSlowdown" in result
        assert len(result) == 2

    def test_gpu_idle(self):
        result = _decode_throttle_reasons(0x0000000000000001)
        assert result == ["GpuIdle"]

    def test_all_reasons(self):
        bitmask = sum(THROTTLE_REASONS.keys())
        result = _decode_throttle_reasons(bitmask)
        assert len(result) == len(THROTTLE_REASONS)

    def test_unknown_bits_ignored(self):
        """Bits not in THROTTLE_REASONS are silently ignored."""
        result = _decode_throttle_reasons(0xFFFF0000)
        assert result == []


class TestThrottleReasonsDict:
    def test_all_values_are_strings(self):
        for bit, name in THROTTLE_REASONS.items():
            assert isinstance(name, str)
            assert isinstance(bit, int)

    def test_expected_reasons_present(self):
        names = set(THROTTLE_REASONS.values())
        assert "HwThermalSlowdown" in names
        assert "SwPowerCap" in names
        assert "GpuIdle" in names
