import struct
from unittest.mock import MagicMock, patch

from gpu_power_monitor.i2c import IT8915Reader
from gpu_power_monitor.protocol import ConnectorReading


def build_payload(rails: list[tuple[int, int]]) -> list[int]:
    """Build a 24-byte payload from (voltage_mv, current_ma) pairs, big-endian.
    Returns list of ints (as read_i2c_block_data returns)."""
    data = b""
    for voltage_mv, current_ma in rails:
        data += struct.pack(">HH", voltage_mv, current_ma)
    return list(data)


class TestIT8915ReaderReadPins:
    @patch("gpu_power_monitor.i2c.SMBus")
    def test_basic_reading(self, mock_smbus_cls):
        """Build a known payload and verify parsed pin readings."""
        rails = [
            (12000, 1000),  # rail 0 -> Pin 6
            (12100, 2000),  # rail 1 -> Pin 5
            (12200, 3000),  # rail 2 -> Pin 4
            (12300, 4000),  # rail 3 -> Pin 3
            (12400, 5000),  # rail 4 -> Pin 2
            (12500, 6000),  # rail 5 -> Pin 1
        ]
        payload = build_payload(rails)
        assert len(payload) == 24

        mock_bus = MagicMock()
        mock_smbus_cls.return_value = mock_bus
        mock_bus.read_i2c_block_data.return_value = payload

        reader = IT8915Reader(bus=1, address=0x2B)
        reader.open()
        result = reader.read_pins()
        reader.close()

        assert result is not None
        assert isinstance(result, ConnectorReading)
        assert len(result.pins) == 6

        # Rail 0 data (12000mV, 1000mA) should map to Pin 6
        pin6 = next(p for p in result.pins if p.pin == 6)
        assert pin6.voltage_mv == 12000
        assert pin6.current_ma == 1000
        assert pin6.label == "Pin 6"

        # Rail 5 data (12500mV, 6000mA) should map to Pin 1
        pin1 = next(p for p in result.pins if p.pin == 1)
        assert pin1.voltage_mv == 12500
        assert pin1.current_ma == 6000
        assert pin1.label == "Pin 1"

        # Verify read_i2c_block_data was called correctly
        mock_bus.read_i2c_block_data.assert_called_once_with(0x2B, 0x80, 24)

    @patch("gpu_power_monitor.i2c.SMBus")
    def test_pin_order_reversal(self, mock_smbus_cls):
        """Verify that rail index i maps to pin (6 - i)."""
        rails = [(11000 + i * 100, 500 + i * 500) for i in range(6)]
        payload = build_payload(rails)

        mock_bus = MagicMock()
        mock_smbus_cls.return_value = mock_bus
        mock_bus.read_i2c_block_data.return_value = payload

        reader = IT8915Reader(bus=1, address=0x2B)
        reader.open()
        result = reader.read_pins()

        # Pins are appended in rail order: first pin has pin_num = 6, last has pin_num = 1
        for idx, pin in enumerate(result.pins):
            expected_pin_num = 6 - idx
            assert pin.pin == expected_pin_num
            expected_voltage = 11000 + idx * 100
            expected_current = 500 + idx * 500
            assert pin.voltage_mv == expected_voltage
            assert pin.current_ma == expected_current

    @patch("gpu_power_monitor.i2c.SMBus")
    def test_voltage_current_conversion(self, mock_smbus_cls):
        """Verify float voltage/current properties."""
        rails = [(12345, 6789)] + [(0, 0)] * 5
        payload = build_payload(rails)

        mock_bus = MagicMock()
        mock_smbus_cls.return_value = mock_bus
        mock_bus.read_i2c_block_data.return_value = payload

        reader = IT8915Reader(bus=1, address=0x2B)
        reader.open()
        result = reader.read_pins()

        pin6 = result.pins[0]  # rail 0 -> Pin 6
        assert pin6.voltage == 12.345
        assert pin6.current == 6.789

    @patch("gpu_power_monitor.i2c.SMBus")
    def test_read_raw_oserror_returns_none(self, mock_smbus_cls):
        """I2C OSError should return None from read_pins."""
        mock_bus = MagicMock()
        mock_smbus_cls.return_value = mock_bus
        mock_bus.read_i2c_block_data.side_effect = OSError("I2C error")

        reader = IT8915Reader(bus=1, address=0x2B)
        reader.open()
        result = reader.read_pins()
        assert result is None

    def test_read_raw_without_open_raises(self):
        """Calling read_raw without opening should raise RuntimeError."""
        reader = IT8915Reader(bus=1, address=0x2B)
        try:
            reader.read_raw()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass
