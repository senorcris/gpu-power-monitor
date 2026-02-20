import struct
import logging
from pathlib import Path
from typing import Optional

from smbus2 import SMBus

from .config import (I2C_BUS, I2C_ADDRESS, I2C_REGISTER, I2C_READ_LENGTH,
                     NUM_PINS, PIN_LABELS, VOLTAGE_MIN, VOLTAGE_MAX, CURRENT_MAX)
from .protocol import PinReading, ConnectorReading

logger = logging.getLogger(__name__)


class IT8915Reader:
    """Reads per-pin voltage/current from IT8915FN via I2C."""

    def __init__(self, bus: int = I2C_BUS, address: int = I2C_ADDRESS,
                 register: int = I2C_REGISTER):
        self.bus_num = bus
        self.address = address
        self.register = register
        self._bus: Optional[SMBus] = None

    def open(self):
        self._bus = SMBus(self.bus_num)

    def close(self):
        if self._bus:
            self._bus.close()
            self._bus = None

    def __enter__(self): self.open(); return self
    def __exit__(self, *args): self.close()

    def read_raw(self) -> Optional[bytes]:
        """Read 24 raw bytes from the IT8915FN register.

        Uses SMBus read_i2c_block_data which works correctly with the NVIDIA
        proprietary Linux driver. Raw i2c_rdwr transactions do not properly
        route through NVIDIA's internal I2C port handling.

        Returns None on error."""
        if not self._bus:
            raise RuntimeError("Bus not opened")
        try:
            data = self._bus.read_i2c_block_data(
                self.address, self.register, I2C_READ_LENGTH
            )
            return bytes(data)
        except OSError as e:
            logger.warning(f"I2C read error: {e}")
            return None

    def read_pins(self) -> Optional[ConnectorReading]:
        """Read and parse all 6 pin readings.
        Returns ConnectorReading or None on error."""
        raw = self.read_raw()
        if raw is None:
            return None

        pins = []
        for i in range(NUM_PINS):
            offset = i * 4
            voltage_mv, current_ma = struct.unpack_from('>HH', raw, offset)

            # Validate readings
            voltage_v = voltage_mv / 1000.0
            current_a = current_ma / 1000.0
            if not (VOLTAGE_MIN <= voltage_v <= VOLTAGE_MAX) and voltage_mv != 0:
                logger.debug(f"Rail {i} voltage out of range: {voltage_v:.3f}V")
            if current_a > CURRENT_MAX:
                logger.debug(f"Rail {i} current out of range: {current_a:.3f}A")

            # Rail 0 = Pin 6, Rail 5 = Pin 1 (reverse mapping)
            pin_num = NUM_PINS - i
            pins.append(PinReading(
                pin=pin_num,
                label=PIN_LABELS[i],
                voltage_mv=voltage_mv,
                current_ma=current_ma,
            ))

        return ConnectorReading(pins=pins)


def find_nvidia_i2c_buses() -> list[dict]:
    """Scan /sys/bus/i2c/devices/ for NVIDIA I2C adapters.
    Returns list of dicts with 'bus' (int) and 'name' (str)."""
    results = []
    i2c_path = Path("/sys/bus/i2c/devices")
    if not i2c_path.exists():
        return results

    for entry in sorted(i2c_path.iterdir()):
        if not entry.name.startswith("i2c-"):
            continue
        name_file = entry / "name"
        if name_file.exists():
            name = name_file.read_text().strip()
            if "NVIDIA" in name.upper():
                bus_num = int(entry.name.split("-")[1])
                results.append({"bus": bus_num, "name": name})
    return results


def probe_buses() -> list[dict]:
    """Probe all NVIDIA I2C buses for IT8915FN at address 0x2B.
    Returns list of results with bus info and hex dump."""
    buses = find_nvidia_i2c_buses()
    results = []

    for bus_info in buses:
        bus_num = bus_info["bus"]
        result = {**bus_info, "address": I2C_ADDRESS, "found": False, "data": None, "pins": None}

        try:
            reader = IT8915Reader(bus=bus_num)
            reader.open()
            try:
                raw = reader.read_raw()
                if raw is not None:
                    result["found"] = True
                    result["data"] = raw.hex()
                    reading = reader.read_pins()
                    if reading:
                        result["pins"] = [
                            {"pin": p.pin, "label": p.label,
                             "voltage_mv": p.voltage_mv, "current_ma": p.current_ma,
                             "voltage": p.voltage, "current": p.current}
                            for p in reading.pins
                        ]
            finally:
                reader.close()
        except OSError as e:
            result["error"] = str(e)

        results.append(result)

    return results
