# gpu-power-monitor

Per-pin power monitoring for the 12V-2x6 GPU connector on Linux. Reads voltage and current from each of the 6 power pins via the IT8915FN I2C chip, alongside standard NVML GPU telemetry, and shows everything in a terminal dashboard.

Built for the ASUS ROG Astral RTX 5090 LC. The per-pin connector monitoring relies on the IT8915FN chip which is specific to certain ASUS ROG cards — other manufacturers don't expose per-pin data this way. Without the IT8915FN, the tool still works as a GPU monitor (power, temp, clocks, VRAM, processes) on any NVIDIA card via NVML.

## Why this exists

The 12V-2x6 connector spec rates each power pin at 9.2A, giving a 662W electrical max across the 6 pins. The RTX 5090 draws up to 575W through that single connector, leaving about 13% margin. Connectors have melted on RTX 50-series cards even with ATX 3.1 certified PSUs and native cables. ASUS ships a Windows-only "Power Detector+" tool in GPU Tweak III that reads per-pin current from the same IT8915FN hardware — this project does the same thing on Linux, with historical graphs and cross-validation between the connector-measured power and what NVML reports the GPU is drawing.

## What you get

- Per-pin voltage, current, and power readings at 2Hz (ASUS ROG cards with IT8915FN only)
- Color-coded pin gauges (green/yellow/red based on ATX 3.1 per-pin current limits)
- Power, VRAM, and temperature graphs with threshold lines
- GPU process table with VRAM usage
- Built-in stress testing (launches PyTorch matrix multiplies)
- Alert log with deduplication — warns on overcurrent, overvoltage, thermal throttling, and connector-vs-GPU power discrepancy
- Daemon mode for headless monitoring (NDJSON over unix socket)

## Install

Python 3.11+, NVIDIA proprietary driver.

```bash
uv sync
```

## Usage

```bash
# launch the TUI (default)
uv run gpu-power-monitor

# daemon mode — polls hardware, serves clients over unix socket
uv run gpu-power-monitor -d

# one-shot JSON dump
uv run gpu-power-monitor --once

# find the IT8915FN on your I2C buses
uv run gpu-power-monitor --probe

# manual I2C override if auto-detect doesn't work
uv run gpu-power-monitor --bus 3 --address 0x2B --register 0x80
```

I2C reads need root or `i2c` group membership (`sudo usermod -aG i2c $USER`, then re-login). Without I2C access the TUI still works — the connector panel stays hidden and you get NVML-only GPU stats.

## TUI keys

`q` quit, `s` stress test, `k` kill process (press twice), `r` clear alerts.

## How it works

ASUS ROG cards with the IT8915FN power monitoring chip expose per-pin voltage and current on an I2C bus routed through the NVIDIA GPU's internal I2C controller. We read 24 bytes from register `0x80` at address `0x2B` — 6 rails x 4 bytes, each rail being a big-endian uint16 millivolts followed by uint16 milliamps.

The daemon polls at 2Hz and pushes newline-delimited JSON snapshots over `/run/user/$UID/gpu-power-monitor.sock`. The TUI tries connecting to the daemon first; if there's no daemon running, it polls hardware directly in a background thread.

Alert thresholds:
- Per-pin current warning at 7.5A, alert at 9.2A (ATX 3.1 connector spec)
- GPU power/thermal thresholds are per-model (RTX 5090 through 5060 Ti) — see `config.py`
- Cross-validates connector power vs NVML-reported power, warns on >20% mismatch

## Tests

```bash
uv run pytest
```
