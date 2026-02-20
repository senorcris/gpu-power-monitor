import json
import time
from gpu_power_monitor.protocol import (
    PinReading, ConnectorReading, GpuStats, GpuProcess, MonitorSnapshot,
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

    def test_round_trip_with_processes(self):
        procs = [
            GpuProcess(pid=1234, name="python", vram_used=512, gpu_util=80),
            GpuProcess(pid=5678, name="Xorg", vram_used=128),
        ]
        snap = MonitorSnapshot(
            connector=None, gpu=None, processes=procs, timestamp=4000.0,
        )
        json_str = snap.to_json()
        restored = MonitorSnapshot.from_json(json_str)

        assert len(restored.processes) == 2
        assert restored.processes[0].pid == 1234
        assert restored.processes[0].name == "python"
        assert restored.processes[0].vram_used == 512
        assert restored.processes[0].gpu_util == 80
        assert restored.processes[1].pid == 5678
        assert restored.processes[1].gpu_util is None

    def test_from_json_missing_processes_field(self):
        """Backward compat: JSON without 'processes' key deserializes to empty list."""
        raw = json.dumps({
            "connector": None, "gpu": None,
            "alerts": [], "timestamp": 5000.0,
        })
        restored = MonitorSnapshot.from_json(raw)
        assert restored.processes == []


class TestGpuStatsThrottleReasons:
    def test_default_throttle_reasons_zero(self):
        g = GpuStats()
        assert g.throttle_reasons == 0

    def test_throttle_reasons_round_trip(self):
        gpu = GpuStats(
            power_draw=100.0, power_limit=350.0, temperature=72,
            name="RTX 5090", throttle_reasons=0x44,
        )
        snap = MonitorSnapshot(connector=None, gpu=gpu, timestamp=6000.0)
        json_str = snap.to_json()
        restored = MonitorSnapshot.from_json(json_str)
        assert restored.gpu.throttle_reasons == 0x44


class TestGpuProcess:
    def test_creation_with_defaults(self):
        p = GpuProcess(pid=42, name="test", vram_used=100)
        assert p.pid == 42
        assert p.name == "test"
        assert p.vram_used == 100
        assert p.gpu_util is None

    def test_creation_with_gpu_util(self):
        p = GpuProcess(pid=99, name="cuda_app", vram_used=2048, gpu_util=55)
        assert p.gpu_util == 55
