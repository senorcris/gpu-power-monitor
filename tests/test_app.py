"""Tests for TUI app module (non-UI logic)."""
from gpu_power_monitor.tui.app import _decode_throttle_reasons, THROTTLE_REASONS


class TestDecodeThrottleReasons:
    def test_no_throttle(self):
        assert _decode_throttle_reasons(0) == []

    def test_single_reason(self):
        result = _decode_throttle_reasons(0x0000000000000004)
        assert result == ["SwPowerCap"]

    def test_multiple_reasons(self):
        bitmask = 0x0000000000000008 | 0x0000000000000040  # HwSlowdown + HwThermalSlowdown
        result = _decode_throttle_reasons(bitmask)
        assert "HwSlowdown" in result
        assert "HwThermalSlowdown" in result
        assert len(result) == 2

    def test_gpu_idle(self):
        result = _decode_throttle_reasons(0x0000000000000001)
        assert result == ["GpuIdle"]

    def test_all_reasons(self):
        bitmask = sum(THROTTLE_REASONS.keys())
        result = _decode_throttle_reasons(bitmask)
        assert len(result) == len(THROTTLE_REASONS)

    def test_unknown_bits_ignored(self):
        """Bits not in THROTTLE_REASONS are silently ignored."""
        result = _decode_throttle_reasons(0xFFFF0000)
        assert result == []


class TestThrottleReasonsDict:
    def test_all_values_are_strings(self):
        for bit, name in THROTTLE_REASONS.items():
            assert isinstance(name, str)
            assert isinstance(bit, int)

    def test_expected_reasons_present(self):
        names = set(THROTTLE_REASONS.values())
        assert "HwThermalSlowdown" in names
        assert "SwPowerCap" in names
        assert "GpuIdle" in names
