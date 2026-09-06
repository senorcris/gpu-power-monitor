"""Behavior and layout regressions for the core monitoring workflows."""
import asyncio
import threading
import time
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from textual.widgets import Button, Input, Static, TabbedContent

from gpu_power_monitor.daemon import _build_alerts, _read_snapshot
from gpu_power_monitor.gpu import PowerLimitConstraints
from gpu_power_monitor.protocol import ConnectorReading, GpuStats, MonitorSnapshot, PinReading, GpuProcess
from gpu_power_monitor.tui.app import GpuPowerMonitorApp, _StressInfo
from gpu_power_monitor.tui.widgets import PowerLimitModal, check_stress_support


def sample(amps=3.0):
    snap = MonitorSnapshot(
        ConnectorReading([PinReading(i, f"Pin {i}", 12000, int(amps * 1000) if i == 1 else 3000)
                          for i in range(1, 7)]),
        GpuStats(name="RTX 5090", power_draw=220, power_limit=575, temperature=63, vram_total=32768),
        [GpuProcess(123, "training.py", 8192), GpuProcess(456, "other-job", 384)],
    )
    snap.alerts = _build_alerts(snap)
    return snap


@pytest.mark.parametrize("size", [(80, 24), (120, 35), (160, 45)])
def test_monitor_layout_and_graph_navigation(size):
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test(size=size) as pilot:
                app._apply_snapshot_inner(sample())
                await pilot.pause()
                assert app._ui("#views", TabbedContent).active == "monitor"
                assert app._ui("#health-status").region.bottom <= 4
                assert app._ui("#pin-row").display
                for i in range(1, 7):
                    assert app._ui(f"#pin-{i}").region.width >= 10
                for name in ("power", "vram", "temp"):
                    assert app._ui(f"#{name}-graph").display
                    assert app._ui(f"#{name}-graph").size.height == 8
                await pilot.press("g")
                await pilot.pause()
                assert app._ui("#vram-graph").region.bottom < size[1]
                assert app._ui("#power-graph").display
                await pilot.press("g")
                await pilot.pause()
                assert app._ui("#temp-graph").region.bottom < size[1]
                await pilot.press("x")
                assert app._ui("#views", TabbedContent).active == ("monitor" if size[0] >= 140 else "processes")
                assert "NORMAL" in str(app._ui("#health-status").render())
    asyncio.run(check())


def test_pin_gauges_reflow_on_live_resize_without_losing_readings():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(160, 45)) as pilot:
                app._apply_snapshot_inner(sample(9.5))
                for width, columns in ((180, 6), (160, 6), (110, 6), (109, 3), (80, 3),
                                       (62, 3), (61, 2), (34, 2), (33, 1), (180, 6)):
                    await pilot.resize_terminal(width, 45)
                    await pilot.pause()
                    grid = app._ui("#pin-row")
                    gauges = [app._ui(f"#pin-{i}") for i in range(1, 7)]
                    assert len({g.region.x for g in gauges}) == columns
                    assert len({g.region.y for g in gauges}) == 6 // columns
                    for gauge in gauges:
                        assert gauge.region.height == 7
                        assert grid.region.x <= gauge.region.x
                        assert gauge.region.right <= grid.region.right <= width
                        assert gauge.region.bottom <= grid.region.bottom
                    assert gauges[0].has_class("alert")
                    assert "9.50A" in str(gauges[0].query_one(".pin-stats", Static).render())
                    for name in ("power", "vram", "temp"):
                        assert app._ui(f"#{name}-graph").display
    asyncio.run(check())


def test_process_sidebar_resize_selection_and_confirmation():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"), patch("os.kill") as kill:
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(139, 45)) as pilot:
                app._apply_snapshot_inner(sample())
                await pilot.press("x", "down")
                table = app._ui("#process-table")
                assert table.cursor_row == 1
                await pilot.resize_terminal(180, 45)
                await pilot.pause()
                views = app._ui("#views", TabbedContent)
                assert views.active == "monitor"
                assert not views.get_tab("processes").display
                assert table.region.right + 2 == app._ui("#monitor-scroll").region.x
                assert table.region.y == app._ui("#pin-1").region.y
                assert app._ui("#processes").region.width == 40
                assert sum(c.width + table.cell_padding * 2 for c in table.ordered_columns) <= table.size.width - 2
                assert table.cursor_row == 1
                await pilot.press("x", "k")
                assert views.active == "monitor"
                assert app._kill_confirm_pid == 456
                await pilot.resize_terminal(139, 45)
                await pilot.pause()
                assert app._kill_confirm_pid is None
                assert views.active == "processes"
                assert views.get_tab("processes").display
                assert app._ui("#processes").styles.margin.right == 0
                assert table.cursor_row == 1
                await pilot.resize_terminal(140, 45)
                await pilot.pause()
                assert table.region.y == app._ui("#pin-1").region.y
                await pilot.press("e")
                assert app._ui("#processes").display
                assert views.active == "events"
                await pilot.press("x", "k", "k")
                kill.assert_called_once_with(456, 15)
    asyncio.run(check())


def test_active_conditions_survive_clear_and_log_only_transitions():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            log = Mock(wraps=app._log_event)
            app._log_event = log
            async with app.run_test() as pilot:
                app._apply_snapshot_inner(sample(7.6))
                initial = log.call_count
                for amps in (7.61, 7.62, 7.63):
                    app._apply_snapshot_inner(sample(amps))
                assert log.call_count == initial
                app.action_clear_log()
                app._apply_snapshot_inner(sample(7.63))
                assert "WARN" in str(app._ui("#health-status").render())
                assert "7.63A" in app._last_alerts["Pin 1 current"]
                app._apply_snapshot_inner(sample(9.5))
                assert log.call_count == initial + 1
                app._apply_snapshot_inner(MonitorSnapshot(None, None))
                assert "Pin 1 current" in app._last_alerts
                assert "Last known" in str(app._ui("#health-status").render())
                app._apply_snapshot_inner(sample())
                assert not app._last_alerts
                assert any("RESOLVED: Pin 1 current" in c.args[0] for c in log.call_args_list)
    asyncio.run(check())


def test_freshness_details_and_samples_during_modal():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test() as pilot:
                snap = sample()
                snap.source = "daemon"
                snap.timestamp = time.time() - 10
                app._apply_snapshot_inner(snap)
                app._tick()
                assert "STALE" in str(app._ui("#health-status").render())
                assert not app._ui("#power-graph").display
                assert not app._power_history
                await pilot.press("a")
                await pilot.pause()
                assert "Daemon" in app.screen.text
                assert "RichVisual" not in app.screen.text
                app._apply_snapshot(sample(9.5))
                assert "ALERT" in str(app._ui("#health-status").render())
                await pilot.press("escape")
                assert "9.50A" in app._last_alerts["Pin 1 current"]
    asyncio.run(check())


def test_power_presets_fit_and_invalid_input_does_not_apply():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(80, 24)) as pilot:
                callback = Mock()
                modal = PowerLimitModal(PowerLimitConstraints(200, 600, 575), 575)
                app.push_screen(modal, callback=callback)
                await pilot.pause()
                dialog = modal.query_one("#pl-dialog").region
                for pct in (100, 80, 70, 60):
                    button = modal.query_one(f"#pl-preset-{pct}").region
                    assert dialog.x <= button.x and button.right <= dialog.right
                    assert dialog.y <= button.y and button.bottom <= dialog.bottom
                assert modal.query_one("#pl-apply").region.bottom < 24
                modal.query_one("#pl-input", Input).value = "9999"
                await pilot.click("#pl-apply")
                callback.assert_not_called()
                assert app.screen is modal
                assert "Nothing has been changed" in str(modal.query_one("#pl-error").render())
                await pilot.click("#pl-preset-80")
                assert modal.query_one("#pl-input", Input).value == "460"
                assert "575W → 460W" in str(modal.query_one("#pl-preview").render())
                await pilot.pause(0.3)  # allow the previous button activation animation to finish
                await pilot.click("#pl-apply")
                await pilot.pause()
                callback.assert_called_once_with(460)
    asyncio.run(check())


def test_stress_missing_dependency_disables_start():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"), patch(
            "gpu_power_monitor.tui.widgets.check_stress_support", return_value=(False, "PyTorch missing")
        ), patch("gpu_power_monitor.tui.widgets.StressTestModal._launch") as launch:
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.press("s")
                await pilot.pause()
                assert app.screen.query_one("#stress-start", Button).disabled
                assert "PyTorch missing" in str(app.screen.query_one("#stress-readiness").render())
                await pilot.click("#stress-start")
                launch.assert_not_called()
                await pilot.press("escape")
    asyncio.run(check())


@pytest.mark.parametrize("code,stopping,expected", [(0, False, "Completed"), (1, False, "FAILED"), (-15, True, "Stopped")])
def test_stress_lifecycle_keeps_final_result(code, stopping, expected):
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"):
            app = GpuPowerMonitorApp()
            async with app.run_test() as pilot:
                proc = Mock(poll=Mock(return_value=None))
                info = _StressInfo(time.time(), 30, "Quick Test", proc, state="Starting", output_done=threading.Event())
                app._stress_tests[123] = info
                info.output.put("GPU_POWER_MONITOR_RUNNING")
                app._tick()
                assert info.state == "Running"
                assert "Running" in str(app._ui("#stress-status").render())
                info.output.put("RuntimeError: CUDA out of memory")
                info.output_done.set()
                info.stopping = stopping
                proc.poll.return_value = code
                app._tick()
                assert not app._stress_tests
                status = str(app._ui("#stress-status").render())
                assert expected in status
                if expected == "FAILED":
                    assert "CUDA out of memory" in status
                app._tick()
                assert str(app._ui("#stress-status").render()) == status
    asyncio.run(check())


def test_terminate_confirmation_names_target_and_cancels_on_navigation():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"), patch("os.kill") as kill:
            app = GpuPowerMonitorApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app._apply_snapshot_inner(sample())
                await pilot.press("x")
                await pilot.pause()
                await pilot.press("k")
                text = str(app._ui("#kill-confirm").render())
                assert "training.py" in text and "PID 123" in text and "SIGTERM" in text
                kill.assert_not_called()
                await pilot.press("down")
                assert app._kill_confirm_pid is None
                await pilot.press("k")
                assert "other-job" in str(app._ui("#kill-confirm").render())
                await pilot.press("k")
                kill.assert_called_once()
                assert kill.call_args.args[0] == 456
    asyncio.run(check())


def test_read_errors_roundtrip_and_reopen_retry():
    reader = Mock(_bus=None)
    reader.open.side_effect = [PermissionError("/dev/i2c-1 denied"), None]
    reader.read_pins.return_value = sample().connector
    gpu = Mock(_handle=object(), last_error="NVML unavailable")
    gpu.read_stats.return_value = None
    gpu.get_processes.return_value = []
    failed = _read_snapshot(reader, gpu)
    restored = MonitorSnapshot.from_json(failed.to_json())
    assert "denied" in restored.errors["connector"]
    assert restored.errors["gpu"] == "NVML unavailable"
    assert _read_snapshot(reader, gpu).connector is not None
    assert reader.open.call_count == 2


def test_stress_support_checks_installed_interpreter():
    with patch("importlib.util.find_spec", return_value=None):
        ready, reason = asyncio.run(check_stress_support())
        assert not ready and "PyTorch" in reason
    from unittest.mock import AsyncMock
    process = Mock(returncode=1, wait=AsyncMock(return_value=1))
    with patch("importlib.util.find_spec", return_value=object()), patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)
    ):
        ready, reason = asyncio.run(check_stress_support())
        assert not ready and "CUDA" in reason


def test_stress_child_output_reaches_failure_history():
    async def check():
        with patch.object(GpuPowerMonitorApp, "_start_reader"), patch(
            "gpu_power_monitor.tui.widgets.check_stress_support", return_value=(True, "Ready")
        ):
            app = GpuPowerMonitorApp()
            async with app.run_test() as pilot:
                # A harmless CPU-only child exercises the real output pipe/thread.
                child = subprocess.Popen(
                    [sys.executable, "-c", "import sys; print('GPU_POWER_MONITOR_RUNNING', flush=True); "
                     "print('RuntimeError: simulated failure', file=sys.stderr); sys.exit(1)"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                try:
                    with patch("gpu_power_monitor.tui.widgets.StressTestModal._launch", return_value=child):
                        await pilot.press("s")
                        await pilot.pause()
                        await pilot.click("#stress-start")
                        for _ in range(20):
                            await pilot.pause(0.05)
                            app._poll_stress()
                            if not app._stress_tests:
                                break
                    assert child.poll() == 1
                    assert "FAILED" in app._latest_event
                    assert "simulated failure" in app._latest_event
                    assert child.stdout.closed
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)
    asyncio.run(check())


def test_legacy_snapshot_without_diagnostics_still_loads():
    import json
    data = json.loads(sample().to_json())
    del data["source"]
    del data["errors"]
    snap = MonitorSnapshot.from_json(json.dumps(data))
    assert snap.source == "direct"
    assert snap.errors == {}
