import logging
from typing import Optional

import pynvml

from .protocol import GpuStats

logger = logging.getLogger(__name__)


class GpuMonitor:
    """Reads GPU statistics via pynvml (NVML)."""

    def __init__(self, gpu_index: int = 0):
        self.gpu_index = gpu_index
        self._handle = None
        self._initialized = False

    def open(self):
        """Initialize NVML and get GPU handle."""
        try:
            pynvml.nvmlInit()
            self._initialized = True
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.gpu_index)
        except pynvml.NVMLError as e:
            logger.error(f"Failed to initialize NVML: {e}")
            raise

    def close(self):
        """Shutdown NVML."""
        if self._initialized:
            try:
                pynvml.nvmlShutdown()
            except pynvml.NVMLError:
                pass
            self._initialized = False
            self._handle = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def read_stats(self) -> Optional[GpuStats]:
        """Read current GPU statistics. Returns GpuStats or None on error."""
        if not self._handle:
            return None

        try:
            # Power
            power_draw = pynvml.nvmlDeviceGetPowerUsage(self._handle) / 1000.0  # mW -> W
            power_limit = pynvml.nvmlDeviceGetEnforcedPowerLimit(self._handle) / 1000.0

            # Temperature
            temperature = pynvml.nvmlDeviceGetTemperature(
                self._handle, pynvml.NVML_TEMPERATURE_GPU)

            # Fan speed (may fail on some configs)
            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(self._handle)
            except pynvml.NVMLError:
                fan_speed = 0

            # Clocks
            clock_graphics = pynvml.nvmlDeviceGetClockInfo(
                self._handle, pynvml.NVML_CLOCK_GRAPHICS)
            clock_memory = pynvml.nvmlDeviceGetClockInfo(
                self._handle, pynvml.NVML_CLOCK_MEM)

            # Utilization
            util = pynvml.nvmlDeviceGetUtilizationRates(self._handle)

            # VRAM
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            vram_used = mem_info.used // (1024 * 1024)  # bytes -> MB
            vram_total = mem_info.total // (1024 * 1024)

            # Name
            name = pynvml.nvmlDeviceGetName(self._handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")

            return GpuStats(
                power_draw=round(power_draw, 1),
                power_limit=round(power_limit, 1),
                temperature=temperature,
                fan_speed=fan_speed,
                clock_graphics=clock_graphics,
                clock_memory=clock_memory,
                util_gpu=util.gpu,
                util_memory=util.memory,
                vram_used=vram_used,
                vram_total=vram_total,
                name=name,
            )
        except pynvml.NVMLError as e:
            logger.warning(f"Error reading GPU stats: {e}")
            return None
