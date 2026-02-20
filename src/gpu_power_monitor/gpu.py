import logging
import subprocess
from typing import Optional

import pynvml

from .protocol import GpuStats, GpuProcess

logger = logging.getLogger(__name__)


class GpuMonitor:
    """Reads GPU statistics via pynvml (NVML)."""

    _NVIDIA_SMI_INTERVAL = 5.0  # seconds between nvidia-smi calls

    def __init__(self, gpu_index: int = 0):
        self.gpu_index = gpu_index
        self._handle = None
        self._initialized = False
        self._smi_cache: list[GpuProcess] = []
        self._smi_cache_time: float = 0

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

            # Throttle reasons
            try:
                throttle_reasons = pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(self._handle)
            except (pynvml.NVMLError, AttributeError):
                throttle_reasons = 0

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
                throttle_reasons=throttle_reasons,
            )
        except pynvml.NVMLError as e:
            logger.warning(f"Error reading GPU stats: {e}")
            return None

    def get_processes(self) -> list[GpuProcess]:
        """Get list of processes using the GPU, merging compute and graphics."""
        if not self._handle:
            return []

        seen: dict[int, GpuProcess] = {}
        try:
            for getter in (
                pynvml.nvmlDeviceGetComputeRunningProcesses,
                pynvml.nvmlDeviceGetGraphicsRunningProcesses,
            ):
                try:
                    procs = getter(self._handle)
                except pynvml.NVMLError:
                    continue
                for p in procs:
                    if p.pid in seen:
                        if p.usedGpuMemory and p.usedGpuMemory // (1024 * 1024) > seen[p.pid].vram_used:
                            seen[p.pid].vram_used = p.usedGpuMemory // (1024 * 1024)
                        continue
                    name = self._resolve_process_name(p.pid)
                    vram = p.usedGpuMemory // (1024 * 1024) if p.usedGpuMemory else 0
                    seen[p.pid] = GpuProcess(pid=p.pid, name=name, vram_used=vram)
        except pynvml.NVMLError as e:
            logger.warning(f"Error listing GPU processes: {e}")

        # Fallback to nvidia-smi when pynvml returns nothing (cached, rate-limited)
        if not seen:
            import time
            now = time.time()
            if now - self._smi_cache_time >= self._NVIDIA_SMI_INTERVAL:
                self._smi_cache_time = now
                smi_result = self._get_processes_nvidia_smi()
                self._smi_cache = list(smi_result.values())
            return sorted(self._smi_cache, key=lambda p: p.vram_used, reverse=True)

        return sorted(seen.values(), key=lambda p: p.vram_used, reverse=True)

    @staticmethod
    def _get_processes_nvidia_smi() -> dict[int, GpuProcess]:
        """Fallback: parse nvidia-smi for GPU process info."""
        seen: dict[int, GpuProcess] = {}
        try:
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-compute-apps=pid,process_name,used_gpu_memory",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    pid = int(parts[0])
                    name = parts[1].rsplit("/", 1)[-1] if "/" in parts[1] else parts[1]
                    try:
                        vram = int(parts[2])
                    except ValueError:
                        vram = 0
                    seen[pid] = GpuProcess(pid=pid, name=name, vram_used=vram)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"nvidia-smi process fallback failed: {e}")
        return seen

    @staticmethod
    def _resolve_process_name(pid: int) -> str:
        """Resolve process name via pynvml or /proc fallback."""
        try:
            name = pynvml.nvmlSystemGetProcessName(pid)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            # nvml returns full path; take basename
            return name.rsplit("/", 1)[-1] if "/" in name else name
        except (pynvml.NVMLError, Exception):
            pass
        try:
            with open(f"/proc/{pid}/comm") as f:
                return f.read().strip()
        except (OSError, FileNotFoundError):
            return f"<{pid}>"
