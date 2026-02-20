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

# Temperature thresholds (celsius)
TEMP_WARN_THRESHOLD = 80
TEMP_ALERT_THRESHOLD = 85

# Graph history
GRAPH_HISTORY_LENGTH = 120  # samples in sparkline buffer (~60s at 2Hz)

# Hardware ID
SUBSYSTEM_ID = 0x89EC1043

# 50-series GPU power baselines (watts)
GPU_POWER_DEFAULTS = {
    "RTX 5090": {
        "tdp_watts": 575,
        "idle_watts_expected": 46,
        "idle_watts_alarm": 80,
        "load_watts_typical": 540,
        "power_warn_watts": 575,
        "power_alarm_watts": 625,
        "power_critical_watts": 660,
    },
    "RTX 5080": {
        "tdp_watts": 360,
        "idle_watts_expected": 13,
        "idle_watts_alarm": 40,
        "load_watts_typical": 340,
        "power_warn_watts": 360,
        "power_alarm_watts": 420,
        "power_critical_watts": 500,
    },
    "RTX 5070 Ti": {
        "tdp_watts": 300,
        "idle_watts_expected": 18,
        "idle_watts_alarm": 40,
        "load_watts_typical": 275,
        "power_warn_watts": 300,
        "power_alarm_watts": 350,
        "power_critical_watts": 420,
    },
    "RTX 5070": {
        "tdp_watts": 250,
        "idle_watts_expected": 15,
        "idle_watts_alarm": 35,
        "load_watts_typical": 235,
        "power_warn_watts": 250,
        "power_alarm_watts": 300,
        "power_critical_watts": 360,
    },
    "RTX 5060 Ti": {
        "tdp_watts": 180,
        "idle_watts_expected": 15,
        "idle_watts_alarm": 30,
        "load_watts_typical": 155,
        "power_warn_watts": 180,
        "power_alarm_watts": 210,
        "power_critical_watts": 260,
    },
}

# 50-series GPU thermal baselines (celsius)
GPU_THERMAL_DEFAULTS = {
    "RTX 5090": {
        "max_temp_spec": 90,
        "throttle_temp": 83,
        "temp_warn": 80,
        "temp_alarm": 85,
        "temp_critical": 90,
    },
    "RTX 5080": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
    },
    "RTX 5070 Ti": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
    },
    "RTX 5070": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
    },
    "RTX 5060 Ti": {
        "max_temp_spec": 87,
        "throttle_temp": 83,
        "temp_warn": 76,
        "temp_alarm": 82,
        "temp_critical": 87,
    },
}

# 12V-2x6 connector specs
CONNECTOR_12V_2X6 = {
    "per_pin_current_max_amps": 9.2,
    "per_pin_current_warn_amps": 8.0,
    "total_power_pins": 6,
    "total_current_max_amps": 55.2,
    "connector_rated_watts": 600,
    "connector_max_watts": 662,
}


def get_gpu_profile(gpu_name: str) -> tuple[dict, dict]:
    """Match a GPU name to its power and thermal profiles.

    Returns (power_defaults, thermal_defaults) for the matched GPU,
    or the RTX 5090 defaults if no match is found.
    """
    for model in ("5090", "5080", "5070 Ti", "5070", "5060 Ti"):
        if model in gpu_name:
            key = f"RTX {model}"
            return GPU_POWER_DEFAULTS[key], GPU_THERMAL_DEFAULTS[key]
    # Default to 5090 (most conservative thresholds)
    return GPU_POWER_DEFAULTS["RTX 5090"], GPU_THERMAL_DEFAULTS["RTX 5090"]


def get_socket_path() -> str:
    uid = os.getuid()
    return f"/run/user/{uid}/gpu-power-monitor.sock"
