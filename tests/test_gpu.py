import builtins
from unittest.mock import MagicMock, patch, mock_open
from types import SimpleNamespace

from gpu_power_monitor.gpu import GpuMonitor


class TestGpuMonitor:
    @patch("gpu_power_monitor.gpu.pynvml")
    def test_read_stats(self, mock_pynvml):
        """Test reading GPU stats with mocked pynvml."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 250500  # mW
        mock_pynvml.nvmlDeviceGetEnforcedPowerLimit.return_value = 350000
        mock_pynvml.nvmlDeviceGetTemperature.return_value = 72
        mock_pynvml.nvmlDeviceGetFanSpeed.return_value = 65
        mock_pynvml.nvmlDeviceGetClockInfo.side_effect = [2100, 1200]
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = SimpleNamespace(gpu=95, memory=60)
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            used=10 * 1024 * 1024 * 1024,  # 10 GB
            total=24 * 1024 * 1024 * 1024,  # 24 GB
        )
        mock_pynvml.nvmlDeviceGetName.return_value = "NVIDIA RTX 4090"
        mock_pynvml.NVML_TEMPERATURE_GPU = 0
        mock_pynvml.NVML_CLOCK_GRAPHICS = 0
        mock_pynvml.NVML_CLOCK_MEM = 1
        mock_pynvml.NVMLError = Exception

        monitor = GpuMonitor(gpu_index=0)
        monitor.open()

        stats = monitor.read_stats()
        assert stats is not None
        assert stats.power_draw == 250.5
        assert stats.power_limit == 350.0
        assert stats.temperature == 72
        assert stats.fan_speed == 65
        assert stats.clock_graphics == 2100
        assert stats.clock_memory == 1200
        assert stats.util_gpu == 95
        assert stats.util_memory == 60
        assert stats.vram_used == 10240
        assert stats.vram_total == 24576
        assert stats.name == "NVIDIA RTX 4090"

        monitor.close()
        mock_pynvml.nvmlShutdown.assert_called_once()

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_read_stats_without_handle_returns_none(self, mock_pynvml):
        """read_stats returns None when handle is not set."""
        mock_pynvml.NVMLError = Exception
        monitor = GpuMonitor()
        assert monitor.read_stats() is None

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_read_stats_nvml_error_returns_none(self, mock_pynvml):
        """read_stats returns None when NVML raises an error."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.NVMLError = Exception
        mock_pynvml.nvmlDeviceGetPowerUsage.side_effect = Exception("NVML fail")

        monitor = GpuMonitor()
        monitor.open()
        assert monitor.read_stats() is None

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_fan_speed_fallback(self, mock_pynvml):
        """Fan speed defaults to 0 when nvmlDeviceGetFanSpeed fails."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 100000
        mock_pynvml.nvmlDeviceGetEnforcedPowerLimit.return_value = 350000
        mock_pynvml.nvmlDeviceGetTemperature.return_value = 50
        mock_pynvml.NVMLError = Exception
        mock_pynvml.nvmlDeviceGetFanSpeed.side_effect = Exception("No fan")
        mock_pynvml.nvmlDeviceGetClockInfo.side_effect = [1800, 1000]
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = SimpleNamespace(gpu=10, memory=5)
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            used=1024 * 1024 * 1024, total=24 * 1024 * 1024 * 1024,
        )
        mock_pynvml.nvmlDeviceGetName.return_value = "Test GPU"
        mock_pynvml.NVML_TEMPERATURE_GPU = 0
        mock_pynvml.NVML_CLOCK_GRAPHICS = 0
        mock_pynvml.NVML_CLOCK_MEM = 1

        monitor = GpuMonitor()
        monitor.open()
        stats = monitor.read_stats()
        assert stats.fan_speed == 0

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_context_manager(self, mock_pynvml):
        """Test __enter__ and __exit__ lifecycle."""
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = MagicMock()
        mock_pynvml.NVMLError = Exception

        with GpuMonitor() as monitor:
            mock_pynvml.nvmlInit.assert_called_once()
            assert monitor._initialized is True

        mock_pynvml.nvmlShutdown.assert_called_once()

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_name_bytes_decoded(self, mock_pynvml):
        """GPU name returned as bytes should be decoded to str."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.nvmlDeviceGetPowerUsage.return_value = 100000
        mock_pynvml.nvmlDeviceGetEnforcedPowerLimit.return_value = 350000
        mock_pynvml.nvmlDeviceGetTemperature.return_value = 50
        mock_pynvml.nvmlDeviceGetFanSpeed.return_value = 50
        mock_pynvml.nvmlDeviceGetClockInfo.side_effect = [1800, 1000]
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = SimpleNamespace(gpu=10, memory=5)
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            used=1024 * 1024 * 1024, total=24 * 1024 * 1024 * 1024,
        )
        mock_pynvml.nvmlDeviceGetName.return_value = b"NVIDIA RTX 4090"
        mock_pynvml.NVML_TEMPERATURE_GPU = 0
        mock_pynvml.NVML_CLOCK_GRAPHICS = 0
        mock_pynvml.NVML_CLOCK_MEM = 1
        mock_pynvml.NVMLError = Exception

        monitor = GpuMonitor()
        monitor.open()
        stats = monitor.read_stats()
        assert stats.name == "NVIDIA RTX 4090"
        assert isinstance(stats.name, str)


class TestGetProcesses:
    @patch("gpu_power_monitor.gpu.pynvml")
    def test_merges_compute_and_graphics(self, mock_pynvml):
        """Processes appearing in both compute and graphics lists are deduped by PID."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.NVMLError = Exception

        compute_proc = SimpleNamespace(pid=100, usedGpuMemory=512 * 1024 * 1024)
        graphics_proc = SimpleNamespace(pid=100, usedGpuMemory=256 * 1024 * 1024)
        unique_proc = SimpleNamespace(pid=200, usedGpuMemory=1024 * 1024 * 1024)

        mock_pynvml.nvmlDeviceGetComputeRunningProcesses.return_value = [compute_proc]
        mock_pynvml.nvmlDeviceGetGraphicsRunningProcesses.return_value = [graphics_proc, unique_proc]
        mock_pynvml.nvmlSystemGetProcessName.return_value = "/usr/bin/python3"

        monitor = GpuMonitor()
        monitor.open()
        procs = monitor.get_processes()

        # Should have 2 unique PIDs, not 3
        assert len(procs) == 2
        pids = {p.pid for p in procs}
        assert pids == {100, 200}

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_merge_keeps_larger_vram(self, mock_pynvml):
        """When same PID appears twice, the larger VRAM value wins."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.NVMLError = Exception

        # Compute reports 256 MB, graphics reports 512 MB
        compute_proc = SimpleNamespace(pid=100, usedGpuMemory=256 * 1024 * 1024)
        graphics_proc = SimpleNamespace(pid=100, usedGpuMemory=512 * 1024 * 1024)

        mock_pynvml.nvmlDeviceGetComputeRunningProcesses.return_value = [compute_proc]
        mock_pynvml.nvmlDeviceGetGraphicsRunningProcesses.return_value = [graphics_proc]
        mock_pynvml.nvmlSystemGetProcessName.return_value = "/usr/bin/python3"

        monitor = GpuMonitor()
        monitor.open()
        procs = monitor.get_processes()

        assert len(procs) == 1
        assert procs[0].vram_used == 512  # larger value

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_sorted_by_vram_descending(self, mock_pynvml):
        """Result is sorted by VRAM descending."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.NVMLError = Exception

        procs = [
            SimpleNamespace(pid=i, usedGpuMemory=i * 100 * 1024 * 1024)
            for i in range(1, 4)
        ]
        mock_pynvml.nvmlDeviceGetComputeRunningProcesses.return_value = procs
        mock_pynvml.nvmlDeviceGetGraphicsRunningProcesses.return_value = []
        mock_pynvml.nvmlSystemGetProcessName.return_value = "app"

        monitor = GpuMonitor()
        monitor.open()
        result = monitor.get_processes()

        vrams = [p.vram_used for p in result]
        assert vrams == sorted(vrams, reverse=True)

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_no_handle_returns_empty(self, mock_pynvml):
        """get_processes returns empty list when handle is not set."""
        mock_pynvml.NVMLError = Exception
        monitor = GpuMonitor()
        assert monitor.get_processes() == []

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_getter_error_skipped(self, mock_pynvml):
        """If one getter raises NVMLError, the other still works."""
        mock_handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = mock_handle
        mock_pynvml.NVMLError = Exception

        mock_pynvml.nvmlDeviceGetComputeRunningProcesses.side_effect = Exception("fail")
        mock_pynvml.nvmlDeviceGetGraphicsRunningProcesses.return_value = [
            SimpleNamespace(pid=42, usedGpuMemory=128 * 1024 * 1024),
        ]
        mock_pynvml.nvmlSystemGetProcessName.return_value = "Xorg"

        monitor = GpuMonitor()
        monitor.open()
        procs = monitor.get_processes()

        assert len(procs) == 1
        assert procs[0].pid == 42


class TestResolveProcessName:
    @patch("gpu_power_monitor.gpu.pynvml")
    def test_nvml_full_path_returns_basename(self, mock_pynvml):
        """Full path from nvml should be trimmed to basename."""
        mock_pynvml.nvmlSystemGetProcessName.return_value = "/usr/bin/python3"
        assert GpuMonitor._resolve_process_name(123) == "python3"

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_nvml_plain_name(self, mock_pynvml):
        """Plain name without slashes returned as-is."""
        mock_pynvml.nvmlSystemGetProcessName.return_value = "myapp"
        assert GpuMonitor._resolve_process_name(123) == "myapp"

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_nvml_bytes_decoded(self, mock_pynvml):
        """Bytes name is decoded to str."""
        mock_pynvml.nvmlSystemGetProcessName.return_value = b"/opt/bin/cuda_app"
        assert GpuMonitor._resolve_process_name(123) == "cuda_app"

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_proc_fallback(self, mock_pynvml):
        """Falls back to /proc/<pid>/comm when nvml fails."""
        mock_pynvml.nvmlSystemGetProcessName.side_effect = Exception("fail")
        mock_pynvml.NVMLError = Exception
        m = mock_open(read_data="firefox\n")
        with patch("builtins.open", m):
            result = GpuMonitor._resolve_process_name(999)
        assert result == "firefox"
        m.assert_called_once_with("/proc/999/comm")

    @patch("gpu_power_monitor.gpu.pynvml")
    def test_all_fallbacks_exhausted(self, mock_pynvml):
        """Returns <pid> when both nvml and /proc fail."""
        mock_pynvml.nvmlSystemGetProcessName.side_effect = Exception("fail")
        mock_pynvml.NVMLError = Exception
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = GpuMonitor._resolve_process_name(404)
        assert result == "<404>"
