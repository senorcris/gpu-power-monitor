# TUI Product Review: GPU Power Monitor

**Date:** 2026-02-20
**Reviewer:** Product review (Claude)
**Hardware target:** NVIDIA RTX 5090 with IT8915FN I2C monitoring on 12V-2x6 connector

---

## 1. Missing Thermals (Critical Gap)

The user flagged this directly: "UI is missing thermals."

### What exists today

- `GpuStats.temperature` is a single integer from `NVML_TEMPERATURE_GPU` (the "edge" sensor).
- It is displayed inline in the gpu-stats bar: `Temp 63C Fan 45%`.
- There is **no temperature graph**, **no hotspot/junction temp**, **no thermal throttle indicator**, and **no thermal alerts**.

### What should exist

| Feature | Priority | Rationale |
|---------|----------|-----------|
| **Temperature time-series graph** | P0 | The RTX 5090 TDP is 575W. Thermal behavior over time is the single most important safety signal after connector current. It should be a graph on par with the power graph, not a single number buried in a text line. |
| **Hotspot / junction temperature** | P0 | NVML exposes `NVML_TEMPERATURE_THRESHOLD_GPU_MAX` and, on Ada/Blackwell, the hotspot temp via `nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)` for edge and additional thermal sensor queries. The hotspot temp is routinely 15-25C higher than the edge temp and is the actual throttle trigger. pynvml may expose this as `NVML_TEMPERATURE_COUNT` sensors. If direct NVML access is insufficient, `nvidia-smi -q -d TEMPERATURE` exposes "GPU Current Temp", "GPU T.Limit Perf Decrease", and "GPU Shutdown Temp". |
| **Thermal throttle warning** | P0 | NVML provides `nvmlDeviceGetCurrentClocksEventReasons()` (or the older `nvmlDeviceGetCurrentClocksThrottleReasons()`). If `nvmlClocksEventReasonSwThermalSlowdown` or `nvmlClocksEventReasonHwThermalSlowdown` is set, the TUI should show a prominent red indicator. This is arguably more important than the per-pin current alerts for day-to-day use. |
| **Thermal alerts in config** | P1 | `config.py` defines `CURRENT_WARN_THRESHOLD` and `CURRENT_ALERT_THRESHOLD` but has **zero** temperature thresholds. Add `TEMP_WARN_THRESHOLD` (e.g., 80C) and `TEMP_ALERT_THRESHOLD` (e.g., 90C). Feed them into the same alert log system. |

### Suggested layout change

Replace the current single `#gpu-stats` 2-line Static with a dedicated thermal row, or add a third graph (`#temp-graph`) alongside power and VRAM. A temperature graph at the same 8-row height as the power graph would cost minimal vertical space and provide high value.

---

## 2. Information Density

### Current layout assessment

The right panel stacks vertically:
1. Pin gauges (6 across) -- ~4 rows
2. Summary line -- 1 row
3. GPU stats -- 2 rows
4. Power graph -- 8 rows
5. VRAM graph -- 8 rows
6. Alert log -- fills remaining

**Issues:**

- **GPU stats line is too dense and too small.** Seven metrics are crammed into 2 lines of plain text: power, temp, fan, GPU%, mem%, core clock, mem clock, VRAM. It reads like a log line, not a dashboard. The most critical values (temp, power) are visually equal to the least critical (mem clock).
- **The VRAM graph takes 8 rows but changes slowly.** VRAM allocation is typically step-function-shaped (process starts, allocates, holds steady, exits). An 8-row time-series graph is overkill for data that barely moves. Consider reducing it to 4 rows or replacing it with a single progress bar + number.
- **No visual hierarchy.** Every element has the same visual weight. The pin gauges, which are the unique selling point of this tool, compete for attention with a VRAM graph.

### Recommendations

- Promote temperature and power to visually dominant positions (large numbers or colored indicators, not inline text).
- Shrink or collapse the VRAM graph. Use the recovered space for a temperature graph.
- Consider a "headline bar" pattern: large bold numbers for total connector power, GPU power draw, and GPU temp -- the three numbers a user glances at most.

---

## 3. Alert System

### Current state

- Alerts fire only on **per-pin current** exceeding warn (7.5A) or alert (9.2A) thresholds.
- Alerts appear in a RichLog at the bottom of the right panel.
- There are no thermal alerts, no voltage alerts, no power limit alerts, and no throttle alerts.

### Gaps

| Missing alert | Impact |
|---------------|--------|
| **Temperature alerts** | A GPU hitting 90C+ with no visible warning is a safety gap. |
| **Voltage out-of-range** | `config.py` defines `VOLTAGE_MIN=10.0` and `VOLTAGE_MAX=13.0` but these are **never checked anywhere in the codebase**. The values exist but are dead code. Under-voltage on the 12V rail is a serious indicator of PSU problems or connector degradation. |
| **Power limit throttling** | When `power_draw` approaches or exceeds `power_limit`, the user should know. |
| **Clock throttle events** | As noted in the thermals section, NVML clock throttle reasons are available and not queried. |
| **Connector total power vs. GPU reported power** | The app has both I2C connector power and NVML-reported GPU power. A significant discrepancy (e.g., connector reads 450W but GPU reports 350W) could indicate sensor calibration issues or unaccounted power paths. This cross-validation is a unique capability of this tool and should be surfaced. |

### Alert UX

- The alert log is append-only with no severity filtering. During a sustained overload, it will flood with repeated identical messages every 0.5s.
- Consider **deduplication** (suppress repeated identical alerts within a window) or **state-based indicators** (a persistent red banner while the condition is active, instead of log spam).

---

## 4. Process Panel UX

### Current state

The left panel (`#left-panel`, `width: 1fr`) occupies roughly 1/3 of the terminal. It shows a DataTable with columns: PID, Name, VRAM (MB), GPU %.

### Assessment

- **Screen real estate vs. information value:** On a single-GPU workstation, there are typically 1-5 GPU processes. A full 1/3 panel for a 5-row table is wasteful.
- **GPU % is often "--":** The `gpu_util` field on `GpuProcess` is `Optional[int]` and is never populated by the current `get_processes()` code (it is always `None`). This means the GPU % column almost always shows "--", wasting a column.
- **No sorting or interaction:** The table is read-only. Users cannot sort by VRAM or GPU%. The cursor exists (for the kill feature) but there is no other interaction.
- **Stress test timer is clever but fragile:** The countdown display (`label (2:34)`) is tied to `_stress_tests` dict which is process-local. If the TUI restarts, tracked stress tests are lost.

### Recommendations

- **Make the process panel collapsible or move it to a bottom bar.** Reclaim the horizontal space for the right panel's graphs and gauges.
- **Alternatively, if keeping the left panel, add value to it:** show per-process power draw (available via NVML on Blackwell: `nvmlDeviceGetProcessUtilization`), or show a process's VRAM as a proportion of total.
- **Fix GPU % population:** Either populate it from `nvmlDeviceGetProcessUtilization()` or remove the column to avoid showing "--" everywhere.
- **Consider a toggle keybinding** (e.g., `p`) to show/hide the process panel.

---

## 5. Missing Features for Power Users

### High priority

1. **Efficiency metric (W per process or W per utilization %).** Users tuning ML training want to know if power consumption is proportional to throughput.

2. **Peak / min / avg statistics.** The TUI shows instantaneous values only. A "session stats" view showing peak connector current, peak temperature, min voltage, and average power would help users characterize their workload after a training run. The data is already flowing through the deques; it just needs min/max/mean tracking.

3. **Export / logging to file.** There is a daemon mode with socket output, but no built-in way to log snapshots to CSV or JSON for post-hoc analysis. A keybinding to start/stop recording, or a `--log-file` CLI flag, would be high value.

4. **PCIe slot power.** The 12V-2x6 connector is only part of the power delivery. The RTX 5090 also draws up to 75W from the PCIe slot. Total board power = connector + slot. Without this, the connector power reading will always be lower than the GPU's reported total power draw, which may confuse users.

### Medium priority

5. **Multi-GPU support.** `GpuMonitor` hardcodes `gpu_index=0`. Users with multiple GPUs (common in ML workstations) cannot monitor a second card.

6. **Color-coded temperature in the gauge area.** Green < 70C, yellow 70-85C, red > 85C. Simple visual encoding.

7. **Clock speed graph or boost state indicator.** Blackwell GPUs dynamically adjust clocks. Seeing clock speed over time alongside power and temp reveals the boost/throttle relationship.

8. **Configuration file support.** All thresholds are hardcoded in `config.py`. Users with different GPUs or connector specs should be able to override thresholds via a TOML/YAML config file or environment variables.

### Low priority

9. **Dark/light theme toggle.** The TUI uses Textual's default theme. Some users prefer light terminals.

10. **Notification integration.** Desktop notifications (via `notify-send` or similar) when critical alerts fire, so the user does not need to keep the TUI visible.

---

## Summary of Top Recommendations

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 1 | Add temperature graph (P0, user-requested) | Small | High |
| 2 | Add hotspot/junction temp reading | Small | High |
| 3 | Add thermal throttle detection via NVML | Small | High |
| 4 | Wire up voltage threshold alerts (dead code today) | Trivial | Medium |
| 5 | Add temperature alert thresholds to config | Trivial | High |
| 6 | Shrink VRAM graph, reclaim space for temp graph | Small | Medium |
| 7 | Add peak/min/avg session statistics | Medium | High |
| 8 | Make process panel collapsible or reduce width | Small | Medium |
| 9 | Fix GPU % column (populate or remove) | Small | Medium |
| 10 | Deduplicate repeated alerts | Small | Medium |
