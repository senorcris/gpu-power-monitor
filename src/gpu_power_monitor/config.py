import os

# I2C configuration (NVIDIA adapter 1, IT8915FN)
I2C_BUS = 1
I2C_ADDRESS = 0x2B
I2C_REGISTER = 0x80
I2C_READ_LENGTH = 24  # 6 rails x 4 bytes

# Pin mapping (rail 0=Pin6, rail 5=Pin1)
NUM_PINS = 6
PIN_LABELS = ["Pin 6", "Pin 5", "Pin 4", "Pin 3", "Pin 2", "Pin 1"]

# Current thresholds (amps)
CURRENT_WARN_THRESHOLD = 7.5
CURRENT_ALERT_THRESHOLD = 9.2  # ASUS spec

# Voltage/current limits
VOLTAGE_NOMINAL = 12.0
VOLTAGE_MIN = 10.0
VOLTAGE_MAX = 13.0
CURRENT_MAX = 15.0

# Refresh rate
REFRESH_RATE = 2.0  # Hz
REFRESH_INTERVAL = 1.0 / REFRESH_RATE

# Hardware ID
SUBSYSTEM_ID = 0x89EC1043


def get_socket_path() -> str:
    uid = os.getuid()
    return f"/run/user/{uid}/gpu-power-monitor.sock"
