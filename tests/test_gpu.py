from unittest.mock import MagicMock, patch
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
