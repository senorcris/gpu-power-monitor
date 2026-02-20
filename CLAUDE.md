# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
uv sync                          # install deps into .venv
uv run gpu-power-monitor         # launch TUI (default mode)
uv run gpu-power-monitor -d      # run as daemon (NDJSON over unix socket)
uv run gpu-power-monitor --once  # single JSON snapshot to stdout
uv run gpu-power-monitor --probe # scan NVIDIA I2C buses for IT8915FN
uv run pytest                    # run all tests
uv run pytest tests/test_gpu.py  # run a single test file
```

Requires root or I2C group permissions for direct hardware reads. The TUI will still launch without I2C access (connector panel stays hidden, GPU stats still work via NVML).

## Architecture

This is a hardware monitoring tool for the 12V-2x6 GPU power connector on ASUS ROG RTX 50-series cards. It reads per-pin voltage/current from an IT8915FN chip over I2C and combines that with NVML GPU telemetry.

### Data flow

```
IT8915FN (I2C) ──→ IT8915Reader ──→ ConnectorReading ──┐
                                                        ├──→ MonitorSnapshot ──→ TUI / daemon
NVML (pynvml)  ──→ GpuMonitor   ──→ GpuStats + procs ──┘
```

### Key modules

- **`protocol.py`** — Dataclasses (`PinReading`, `ConnectorReading`, `GpuStats`, `GpuProcess`, `MonitorSnapshot`) and JSON serialization. This is the shared data contract between all components.
- **`i2c.py`** — `IT8915Reader` talks to IT8915FN via smbus2. Reads 24 bytes (6 rails × 4 bytes: big-endian uint16 voltage_mv + uint16 current_ma). Rail-to-pin mapping is reversed (rail 0 = Pin 6).
- **`gpu.py`** — `GpuMonitor` wraps pynvml for GPU stats and process listing. Falls back to nvidia-smi subprocess when pynvml returns empty process lists.
- **`daemon.py`** — Async daemon that polls both sources, broadcasts NDJSON snapshots over a Unix socket (`/run/user/$UID/gpu-power-monitor.sock`), and runs alert threshold checks.
- **`config.py`** — All constants: I2C addresses, thresholds, refresh rate (2Hz), per-GPU-model power/thermal baselines for the 50-series lineup.
- **`tui/app.py`** — Textual app. Tries connecting to daemon socket first, falls back to direct hardware polling in a background thread. Renders pin gauges, power/VRAM/temp graphs (plotext), process table, and alert log.
- **`tui/widgets.py`** — `PinGauge` widget (per-pin current bar with color thresholds) and `StressTestModal` (launches PyTorch matrix multiply stress tests as subprocesses).

### Daemon vs TUI

The TUI can run standalone (direct polling) or as a client of the daemon. The daemon is the intended production mode — it holds the I2C bus open and serves multiple clients. The TUI auto-detects the daemon socket on startup.

### Alert system

Thresholds in `config.py` drive alerts in both daemon and TUI (duplicated in `_apply_snapshot_inner` for the direct-polling path). Alerts are deduplicated per cycle in the TUI. Cross-validation compares I2C connector power vs NVML-reported power and warns on >20% discrepancy.
