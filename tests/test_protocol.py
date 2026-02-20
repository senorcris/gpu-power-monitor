import json
import time
from gpu_power_monitor.protocol import (
    PinReading, ConnectorReading, GpuStats, MonitorSnapshot,
)


class TestPinReading:
    def test_voltage_conversion(self):
        p = PinReading(pin=1, label="Pin 1", voltage_mv=12050, current_ma=5500)
        assert p.voltage == 12.05

    def test_current_conversion(self):
        p = PinReading(pin=1, label="Pin 1", voltage_mv=12000, current_ma=7500)
        assert p.current == 7.5

    def test_power_calculation(self):
        p = PinReading(pin=1, label="Pin 1", voltage_mv=12000, current_ma=2000)
        assert p.power == 24.0  # 12V * 2A

    def test_zero_values(self):
        p = PinReading(pin=1, label="Pin 1", voltage_mv=0, current_ma=0)
        assert p.voltage == 0.0
        assert p.current == 0.0
        assert p.power == 0.0


class TestConnectorReading:
    def _make_pins(self, count=6):
        return [
            PinReading(pin=i + 1, label=f"Pin {i + 1}",
                       voltage_mv=12000, current_ma=1000 * (i + 1))
            for i in range(count)
        ]

    def test_total_current(self):
        pins = self._make_pins()
        r = ConnectorReading(pins=pins)
        # 1 + 2 + 3 + 4 + 5 + 6 = 21 A
        assert r.total_current == 21.0

    def test_total_power(self):
        pins = self._make_pins()
        r = ConnectorReading(pins=pins)
        # Each pin: 12V * (i+1)A => 12 + 24 + 36 + 48 + 60 + 72 = 252 W
        assert r.total_power == 252.0

    def test_timestamp_set(self):
        before = time.time()
        r = ConnectorReading(pins=[])
        after = time.time()
        assert before <= r.timestamp <= after


class TestMonitorSnapshotSerialization:
    def test_round_trip_full(self):
        pins = [
            PinReading(pin=i, label=f"Pin {i}", voltage_mv=12000 + i, current_ma=3000 + i)
            for i in range(1, 7)
        ]
        connector = ConnectorReading(pins=pins, timestamp=1000.0)
        gpu = GpuStats(
            power_draw=250.5, power_limit=350.0, temperature=72,
            fan_speed=65, clock_graphics=2100, clock_memory=1200,
            util_gpu=95, util_memory=60, vram_used=10000, vram_total=24000,
            name="NVIDIA RTX 4090",
        )
        snap = MonitorSnapshot(
            connector=connector, gpu=gpu,
            alerts=["High current on Pin 3"], timestamp=2000.0,
        )
        json_str = snap.to_json()
        restored = MonitorSnapshot.from_json(json_str)

        assert restored.timestamp == 2000.0
        assert restored.alerts == ["High current on Pin 3"]
        assert restored.gpu.name == "NVIDIA RTX 4090"
        assert restored.gpu.power_draw == 250.5
        assert restored.connector.timestamp == 1000.0
        assert len(restored.connector.pins) == 6
        assert restored.connector.pins[0].pin == 1
        assert restored.connector.pins[0].voltage_mv == 12001

    def test_round_trip_none_fields(self):
        snap = MonitorSnapshot(connector=None, gpu=None, timestamp=3000.0)
        json_str = snap.to_json()
        restored = MonitorSnapshot.from_json(json_str)
        assert restored.connector is None
        assert restored.gpu is None
        assert restored.alerts == []

    def test_json_is_ndjson(self):
        snap = MonitorSnapshot(connector=None, gpu=None)
        assert snap.to_json().endswith("\n")
        # Should be parseable without the trailing newline
        json.loads(snap.to_json().strip())
