# GPU Power Monitor

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Linux](https://img.shields.io/badge/platform-Linux-FCC624.svg?logo=linux&logoColor=black)](https://github.com/senorcris/gpu-power-monitor)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**See how much power each pin of your GPU's 12V-2x6 connector is carrying—not just the total.**

GPU Power Monitor is an open-source Linux terminal dashboard for NVIDIA GPUs. On supported ASUS ROG cards it reads voltage and current from all six 12V power pins through the onboard IT8915FN controller. It combines those readings with NVML telemetry so you can spot uneven current distribution, overloaded pins, voltage problems, and differences between connector input power and GPU-reported power.

On cards without accessible per-pin telemetry, it still works as a full NVML dashboard for power, temperature, clocks, utilization, VRAM, and GPU processes.

![GPU Power Monitor terminal dashboard showing six connector pin gauges and GPU history graphs](img/screenshot.svg)

## Why per-pin monitoring matters

Tools such as `nvidia-smi` report total GPU power. That total cannot show whether one connector contact is carrying substantially more current than the others.

A 12V-2x6 connector has six +12 V power contacts. At a 9.2 A per-pin limit, a high-power card has little room for poor contact or uneven load distribution. GPU Power Monitor makes those individual rails visible on Linux and provides:

- Live voltage, current, and calculated power for each of the six pins
- Green, yellow, and red gauges based on per-pin current thresholds
- Total connector power compared with NVML-reported GPU power
- Rolling power, VRAM, and temperature graphs sampled at 2 Hz
- Alerts for pin overcurrent, abnormal voltage, high GPU power or temperature, and measurement discrepancies
- GPU process monitoring, power-limit controls, and an optional PyTorch stress test
- One-shot JSON and an NDJSON Unix-socket daemon for scripts and headless monitoring

This is the Linux counterpart to the per-pin visibility provided by ASUS Power Detector+ on supported Windows systems.

## Hardware support

| Capability | Support |
| --- | --- |
| Per-pin 12V-2x6 telemetry | **Verified:** ASUS ROG Astral RTX 5090 LC with IT8915FN |
| Other ASUS ROG cards with IT8915FN | May work, but needs community verification |
| Standard GPU telemetry | NVIDIA GPUs supported by the proprietary driver and NVML |
| AMD and Intel GPUs | Not currently supported |

Per-pin monitoring depends on board-level hardware and firmware; having a 12V-2x6 connector alone is not enough. Other vendors may use different controllers or expose no per-pin data. If your card responds to the probe, please share the exact model and PCI subsystem ID in a [hardware support report](https://github.com/senorcris/gpu-power-monitor/issues)—it will help expand this table.

## Quick start

Requirements:

- Linux and Python 3.11 or newer
- An NVIDIA proprietary driver with working `nvidia-smi`
- [`uv`](https://docs.astral.sh/uv/) for installation
- Access to `/dev/i2c-*` for per-pin readings; not required for NVML-only mode

```bash
git clone https://github.com/senorcris/gpu-power-monitor.git
cd gpu-power-monitor
uv sync
uv run gpu-power-monitor
```

The dashboard starts in NVML-only mode if the connector controller cannot be opened. This makes it safe to try before configuring I2C permissions.

### Enable per-pin readings

First, check that Linux exposes I2C devices and probe the NVIDIA adapters:

```bash
ls /dev/i2c-*
uv run gpu-power-monitor --probe
```

I2C access normally requires root or membership in the `i2c` group:

```bash
sudo usermod -aG i2c "$USER"
```

Log out and back in after changing group membership. Distribution-specific udev rules may also be needed. Avoid running the entire dashboard as root when group or udev permissions will do.

A successful probe prints six plausible voltage/current pairs. If auto-detection finds the controller on a non-default bus, pass that bus when launching:

```bash
uv run gpu-power-monitor --bus 3
```

The known protocol defaults are I2C address `0x2b`, register `0x80`, and a 24-byte read. They can be overridden for hardware research:

```bash
uv run gpu-power-monitor --bus 3 --address 0x2b --register 0x80
```

> [!CAUTION]
> Direct I2C access is intended for experienced Linux users. The monitor performs reads, but probing undocumented GPU buses is inherently hardware-specific. Validate results before relying on alerts; this tool is diagnostic software, not a replacement for a fully seated cable, sound hardware, or thermal inspection.

## Usage

```bash
# Interactive terminal dashboard (default)
uv run gpu-power-monitor

# One newline-terminated JSON snapshot
uv run gpu-power-monitor --once

# Discover the controller on NVIDIA I2C adapters
uv run gpu-power-monitor --probe

# Foreground daemon: streams NDJSON to connected Unix-socket clients
uv run gpu-power-monitor --daemon

# Show every option
uv run gpu-power-monitor --help
```

The daemon listens on `/run/user/$UID/gpu-power-monitor.sock`. The TUI automatically uses it when available and falls back to polling the hardware directly when it is not.

### Keyboard controls

| Key | Action |
| --- | --- |
| `q` | Quit |
| `r` | Clear the alert log |
| `s` | Start a GPU stress-test preset (requires CUDA-enabled PyTorch in the environment) |
| `p` | Change the GPU power limit (requires appropriate NVIDIA permissions) |
| `k` | Send `SIGTERM` to the selected process; press twice to confirm |

## How it works

On the verified ASUS board, an IT8915FN monitoring controller is reachable through an NVIDIA I2C adapter. GPU Power Monitor reads 24 bytes from register `0x80` at address `0x2b`:

```text
6 rails × 4 bytes
└─ per rail: uint16 voltage_mV + uint16 current_mA (big-endian)
```

The rail order is reversed relative to the physical pin labels: rail 0 maps to pin 6 and rail 5 maps to pin 1. Per-pin power is calculated as voltage × current, then summed for connector input power.

```text
IT8915FN over I2C ──> six pin readings ──┐
                                         ├──> snapshot ──> TUI / JSON / daemon
NVIDIA NVML ─────────> GPU + processes ──┘
```

The connector total and NVML power are measured at different points, so they are not expected to be identical. A difference greater than 20% under meaningful load is surfaced as a diagnostic warning.

Default alert points include:

- Per-pin current warning at 7.5 A and alert at 9.2 A
- Pin voltage outside 10–13 V
- Model-specific power and temperature thresholds for RTX 50-series cards
- Connector-versus-NVML power difference greater than 20% when both exceed 50 W

## Help add support for more cards

Hardware reports are especially valuable. Open an [issue](https://github.com/senorcris/gpu-power-monitor/issues) with:

- Exact GPU manufacturer and model
- Linux distribution, kernel, and NVIDIA driver version
- PCI IDs from `lspci -nn -v -d 10de:`
- Sanitized output from `uv run gpu-power-monitor --probe`
- Whether the six readings are stable and plausible at idle and under load

Please do not guess at registers by writing to an unknown I2C device. New controller support should begin with documented or independently validated read-only behavior.

## Development

```bash
uv sync
uv run pytest
```

Contributions are welcome—particularly verified card reports, controller research, safer device detection, packaging, documentation, and tests. Please include tests for behavior changes and keep hardware access mockable so the suite can run without an NVIDIA GPU.

## License

[MIT](LICENSE)
