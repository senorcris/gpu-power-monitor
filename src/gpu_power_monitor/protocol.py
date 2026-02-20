from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import time


@dataclass
class PinReading:
    pin: int  # 1-6
    label: str  # "Pin 1" through "Pin 6"
    voltage_mv: int  # raw millivolts
    current_ma: int  # raw milliamps

    @property
    def voltage(self) -> float:
        return self.voltage_mv / 1000.0

    @property
    def current(self) -> float:
        return self.current_ma / 1000.0

    @property
    def power(self) -> float:
        return self.voltage * self.current


@dataclass
class ConnectorReading:
    pins: list[PinReading]
    timestamp: float = field(default_factory=time.time)

    @property
    def total_current(self) -> float:
        return sum(p.current for p in self.pins)

    @property
    def total_power(self) -> float:
        return sum(p.power for p in self.pins)


@dataclass
class GpuProcess:
    pid: int
    name: str
    vram_used: int  # MB
    gpu_util: Optional[int] = None  # percent, may not be available


@dataclass
class GpuStats:
    power_draw: float = 0.0  # watts
    power_limit: float = 0.0  # watts
    temperature: int = 0  # celsius
    fan_speed: int = 0  # percent
    clock_graphics: int = 0  # MHz
    clock_memory: int = 0  # MHz
    util_gpu: int = 0  # percent
    util_memory: int = 0  # percent
    vram_used: int = 0  # MB
    vram_total: int = 0  # MB
    name: str = ""
    throttle_reasons: int = 0  # bitmask from nvmlDeviceGetCurrentClocksThrottleReasons


@dataclass
class MonitorSnapshot:
    connector: Optional[ConnectorReading]
    gpu: Optional[GpuStats]
    processes: list[GpuProcess] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialize to JSON string (newline-terminated for NDJSON)."""
        d = asdict(self)
        return json.dumps(d) + "\n"

    @classmethod
    def from_json(cls, data: str) -> "MonitorSnapshot":
        """Deserialize from JSON string."""
        d = json.loads(data)
        connector = None
        if d.get("connector") is not None:
            c = d["connector"]
            pins = [PinReading(**p) for p in c["pins"]]
            connector = ConnectorReading(pins=pins, timestamp=c["timestamp"])
        gpu = None
        if d.get("gpu") is not None:
            gpu = GpuStats(**d["gpu"])
        processes = [GpuProcess(**p) for p in d.get("processes", [])]
        return cls(
            connector=connector,
            gpu=gpu,
            processes=processes,
            alerts=d.get("alerts", []),
            timestamp=d["timestamp"],
        )
