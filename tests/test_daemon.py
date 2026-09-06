"""Tests for daemon alert logic."""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gpu_power_monitor.daemon import _broadcast
from gpu_power_monitor.daemon import _build_alerts
from gpu_power_monitor.config import GPU_THERMAL_DEFAULTS
from gpu_power_monitor.protocol import (
    PinReading, ConnectorReading, GpuStats, MonitorSnapshot,
)


def _make_pin(pin=1, voltage_mv=12000, current_ma=3000):
    return PinReading(pin=pin, label=f"Pin {pin}", voltage_mv=voltage_mv, current_ma=current_ma)


def _make_connector(pins=None, **kwargs):
    if pins is None:
        pins = [_make_pin(i) for i in range(1, 7)]
    return ConnectorReading(pins=pins, **kwargs)


def _make_gpu(**overrides):
    defaults = dict(
        power_draw=200.0, power_limit=350.0, temperature=60,
        fan_speed=50, clock_graphics=2100, clock_memory=1200,
        util_gpu=50, util_memory=30, vram_used=4096, vram_total=24000,
        name="NVIDIA GeForce RTX 5090", throttle_reasons=0,
    )
    defaults.update(overrides)
    return GpuStats(**defaults)


@pytest.mark.parametrize("disconnect", [False, True])
def test_broadcast_survives_client_changes(disconnect):
    async def check():
        first = Mock(drain=AsyncMock())
        other = Mock(drain=AsyncMock())
        clients = {first}

        async def change_clients():
            await asyncio.sleep(0)
            if disconnect:
                clients.discard(first)
            else:
                clients.add(other)

        first.drain.side_effect = change_clients
        await _broadcast(clients, b"first\n")
        first.write.assert_called_once_with(b"first\n")
        other.write.assert_not_called()
        first.drain.side_effect = None
        await _broadcast(clients, b"second\n")
        if disconnect:
            assert first.write.call_count == 1
        else:
            other.write.assert_called_once_with(b"second\n")

    asyncio.run(check())


def test_broadcast_drops_stalled_and_broken_clients():
    async def check():
        stalled = Mock(drain=AsyncMock())
        broken = Mock(drain=AsyncMock(side_effect=BrokenPipeError))
        healthy = Mock(drain=AsyncMock())
        clients = {stalled, broken, healthy}

        async def never_drains():
            await asyncio.Event().wait()

        stalled.drain.side_effect = never_drains
        with patch("gpu_power_monitor.daemon.REFRESH_INTERVAL", 0.01):
            await asyncio.wait_for(_broadcast(clients, b"first\n"), timeout=1)
        assert clients == {healthy}
        stalled.transport.abort.assert_called_once()
        broken.transport.abort.assert_called_once()
        healthy.transport.abort.assert_not_called()
        await _broadcast(clients, b"second\n")
        assert healthy.write.call_count == 2

    asyncio.run(check())


class TestBuildAlerts:
    @pytest.mark.parametrize("model", list(GPU_THERMAL_DEFAULTS))
    @pytest.mark.parametrize("boundary", ["below", "warn", "alarm"])
    def test_model_thermal_thresholds(self, model, boundary):
        profile = GPU_THERMAL_DEFAULTS[model]
        temperature = {
            "below": profile["temp_warn"] - 1,
            "warn": profile["temp_warn"],
            "alarm": profile["temp_alarm"],
        }[boundary]
        snap = MonitorSnapshot(None, _make_gpu(name=model, temperature=temperature))
        thermal_alerts = [a for a in _build_alerts(snap) if "temperature" in a]
        if boundary == "below":
            assert thermal_alerts == []
        else:
            severity = "WARN" if boundary == "warn" else "ALERT"
            assert len(thermal_alerts) == 1
            assert thermal_alerts[0].startswith(severity)
            assert f"{temperature}C" in thermal_alerts[0]

    def test_no_alerts_normal_conditions(self):
        snap = MonitorSnapshot(connector=_make_connector(), gpu=_make_gpu())
        alerts = _build_alerts(snap)
        assert alerts == []

    def test_current_warn_threshold(self):
        pin = _make_pin(pin=1, current_ma=7600)  # 7.6A > 7.5A warn
        snap = MonitorSnapshot(connector=_make_connector(pins=[pin]), gpu=None)
        alerts = _build_alerts(snap)
        assert len(alerts) == 1
        assert "WARN" in alerts[0]
        assert "Pin 1" in alerts[0]

    def test_current_alert_threshold(self):
        pin = _make_pin(pin=3, current_ma=9500)  # 9.5A > 9.2A alert
        snap = MonitorSnapshot(connector=_make_connector(pins=[pin]), gpu=None)
        alerts = _build_alerts(snap)
        assert len(alerts) == 1
        assert "ALERT" in alerts[0]
        assert "Pin 3" in alerts[0]

    def test_voltage_below_minimum(self):
        pin = _make_pin(pin=2, voltage_mv=9500)  # 9.5V < 10.0V
        snap = MonitorSnapshot(connector=_make_connector(pins=[pin]), gpu=None)
        alerts = _build_alerts(snap)
        assert any("below" in a and "voltage" in a for a in alerts)

    def test_voltage_above_maximum(self):
        pin = _make_pin(pin=4, voltage_mv=13500)  # 13.5V > 13.0V
        snap = MonitorSnapshot(connector=_make_connector(pins=[pin]), gpu=None)
        alerts = _build_alerts(snap)
        assert any("above" in a and "voltage" in a for a in alerts)

    def test_zero_voltage_no_alert(self):
        """Zero voltage (disconnected pin) should not trigger low-voltage alert."""
        pin = _make_pin(pin=1, voltage_mv=0, current_ma=0)
        snap = MonitorSnapshot(connector=_make_connector(pins=[pin]), gpu=None)
        alerts = _build_alerts(snap)
        assert not any("voltage" in a for a in alerts)

    def test_temp_warn_threshold(self):
        gpu = _make_gpu(temperature=82)  # > 80C warn
        snap = MonitorSnapshot(connector=None, gpu=gpu)
        alerts = _build_alerts(snap)
        assert any("WARN" in a and "temperature" in a for a in alerts)

    def test_temp_alert_threshold(self):
        gpu = _make_gpu(temperature=87)  # > 85C alert
        snap = MonitorSnapshot(connector=None, gpu=gpu)
        alerts = _build_alerts(snap)
        assert any("ALERT" in a and "temperature" in a for a in alerts)

    def test_normal_temp_no_alert(self):
        gpu = _make_gpu(temperature=70)
        snap = MonitorSnapshot(connector=None, gpu=gpu)
        alerts = _build_alerts(snap)
        assert not any("temperature" in a for a in alerts)

    def test_model_specific_power_warn(self):
        """Power exceeding model-specific warn threshold generates WARN."""
        gpu = _make_gpu(power_draw=580.0, name="NVIDIA GeForce RTX 5090")
        snap = MonitorSnapshot(connector=None, gpu=gpu)
        alerts = _build_alerts(snap)
        assert any("WARN" in a and "power" in a.lower() for a in alerts)

    def test_model_specific_power_alarm(self):
        """Power exceeding model-specific alarm threshold generates ALERT."""
        gpu = _make_gpu(power_draw=630.0, name="NVIDIA GeForce RTX 5090")
        snap = MonitorSnapshot(connector=None, gpu=gpu)
        alerts = _build_alerts(snap)
        assert any("ALERT" in a and "power" in a.lower() for a in alerts)

    def test_cross_validation_large_discrepancy(self):
        """Connector vs GPU power >20% discrepancy generates WARN."""
        # Connector: 6 pins * 12V * 5A = 360W, GPU reports 250W -> >20% diff
        pins = [_make_pin(i, voltage_mv=12000, current_ma=5000) for i in range(1, 7)]
        gpu = _make_gpu(power_draw=250.0)
        snap = MonitorSnapshot(connector=_make_connector(pins=pins), gpu=gpu)
        alerts = _build_alerts(snap)
        assert any("discrepancy" in a for a in alerts)

    def test_cross_validation_small_discrepancy_no_alert(self):
        """Connector vs GPU power within 20% should not alert."""
        # Connector: 6 pins * 12V * 3A = 216W, GPU reports 200W -> ~8% diff
        pins = [_make_pin(i, voltage_mv=12000, current_ma=3000) for i in range(1, 7)]
        gpu = _make_gpu(power_draw=200.0)
        snap = MonitorSnapshot(connector=_make_connector(pins=pins), gpu=gpu)
        alerts = _build_alerts(snap)
        assert not any("discrepancy" in a for a in alerts)

    def test_cross_validation_low_power_skipped(self):
        """Cross-validation skipped when power < 50W (idle conditions)."""
        pins = [_make_pin(i, voltage_mv=12000, current_ma=500) for i in range(1, 7)]
        gpu = _make_gpu(power_draw=30.0)
        snap = MonitorSnapshot(connector=_make_connector(pins=pins), gpu=gpu)
        alerts = _build_alerts(snap)
        assert not any("discrepancy" in a for a in alerts)

    def test_none_connector_no_crash(self):
        snap = MonitorSnapshot(connector=None, gpu=_make_gpu())
        alerts = _build_alerts(snap)
        assert isinstance(alerts, list)

    def test_none_gpu_no_crash(self):
        snap = MonitorSnapshot(connector=_make_connector(), gpu=None)
        alerts = _build_alerts(snap)
        assert isinstance(alerts, list)

    def test_both_none_empty_alerts(self):
        snap = MonitorSnapshot(connector=None, gpu=None)
        alerts = _build_alerts(snap)
        assert alerts == []
