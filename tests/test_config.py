"""Tests for config module."""
from gpu_power_monitor.config import (
    get_gpu_profile, get_socket_path,
    GPU_POWER_DEFAULTS, GPU_THERMAL_DEFAULTS, CONNECTOR_12V_2X6,
)


class TestGetGpuProfile:
    def test_rtx_5090_match(self):
        power, thermal = get_gpu_profile("NVIDIA GeForce RTX 5090")
        assert power["tdp_watts"] == 575
        assert thermal["max_temp_spec"] == 90

    def test_rtx_5080_match(self):
        power, thermal = get_gpu_profile("NVIDIA GeForce RTX 5080")
        assert power["tdp_watts"] == 360

    def test_rtx_5070_ti_match(self):
        power, thermal = get_gpu_profile("RTX 5070 Ti")
        assert power["tdp_watts"] == 300

    def test_rtx_5070_match(self):
        power, thermal = get_gpu_profile("RTX 5070")
        assert power["tdp_watts"] == 250

    def test_rtx_5060_ti_match(self):
        power, thermal = get_gpu_profile("RTX 5060 Ti")
        assert power["tdp_watts"] == 180

    def test_unknown_defaults_to_5090(self):
        power, thermal = get_gpu_profile("Unknown GPU Model")
        assert power == GPU_POWER_DEFAULTS["RTX 5090"]
        assert thermal == GPU_THERMAL_DEFAULTS["RTX 5090"]

    def test_5070_ti_matches_before_5070(self):
        """Ensure '5070 Ti' matches before '5070'."""
        power, _ = get_gpu_profile("RTX 5070 Ti Founders Edition")
        assert power["tdp_watts"] == 300  # 5070 Ti, not 5070 (250)


class TestGpuDefaults:
    def test_all_power_keys_present(self):
        required = {"tdp_watts", "idle_watts_expected", "idle_watts_alarm",
                     "load_watts_typical", "power_warn_watts",
                     "power_alarm_watts", "power_critical_watts"}
        for model, profile in GPU_POWER_DEFAULTS.items():
            assert required.issubset(profile.keys()), f"Missing keys in {model}"

    def test_all_thermal_keys_present(self):
        required = {"max_temp_spec", "throttle_temp", "temp_warn",
                     "temp_alarm", "temp_critical"}
        for model, profile in GPU_THERMAL_DEFAULTS.items():
            assert required.issubset(profile.keys()), f"Missing keys in {model}"

    def test_connector_specs(self):
        assert CONNECTOR_12V_2X6["per_pin_current_max_amps"] == 9.2
        assert CONNECTOR_12V_2X6["total_power_pins"] == 6
        assert CONNECTOR_12V_2X6["connector_rated_watts"] == 600


class TestGetSocketPath:
    def test_returns_string(self):
        path = get_socket_path()
        assert isinstance(path, str)
        assert "gpu-power-monitor.sock" in path
