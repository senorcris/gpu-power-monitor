# NVIDIA RTX 50-Series GPU Power & Thermal Baselines

> Research date: 2026-02-20
> Purpose: Config defaults for GPU power monitoring tool

---

## Summary Table

| Spec | RTX 5090 | RTX 5080 | RTX 5070 Ti | RTX 5070 | RTX 5060 Ti |
|------|----------|----------|-------------|----------|-------------|
| **TDP / TBP (W)** | 575 | 360 | 300 | 250 | 180 |
| **Idle Power (W)** | 40-50 | 12-15 | 17-21 | 14-17 | 14-17 |
| **Typical Load (W)** | 500-560 | 320-350 | 260-290 | 220-245 | 140-165 |
| **Max Measured (W)** | 575-600 | 360-400 | 300-350 | 250-275 | 180-205 |
| **Peak Transient (W)** | ~900 (sub-1ms) | ~500+ | ~400+ | ~350+ | ~250 (est.) |
| **Power Limit Range** | 100% (FE), AIB up to 104% | 100% (FE), AIB up to 125% | 83-100% (FE), AIB varies | 100-110% (FE) | 100% typical |
| **Max GPU Temp (C)** | 90 | 88 | 88 | 88 | 87 (est.) |
| **Thermal Throttle (C)** | 83-84 | 83-84 | 83-88 | 83-88 | ~83 (est.) |
| **Typical Gaming Temp (C)** | 68-75 | 60-68 | 60-67 | 58-65 | 55-65 |
| **VRAM** | 32 GB GDDR7 | 16 GB GDDR7 | 16 GB GDDR7 | 12 GB GDDR7 | 16 GB GDDR7 |
| **Memory Bus** | 512-bit | 256-bit | 256-bit | 192-bit | 128-bit |
| **Power Connector** | 1x 12V-2x6 | 1x 12V-2x6 | 1x 12V-2x6 | 1x 12V-2x6 | 1x 8-pin PCIe |
| **PSU Recommendation** | 1000-1100W | 850W | 750W | 650W | 550-650W |

---

## Detailed Per-Model Data

### RTX 5090

- **GPU:** GB202 (Blackwell)
- **TDP/TBP:** 575W
- **Idle Power:** ~46W (FE measured by GamersNexus); some models 40-50W depending on monitor config
- **Typical Gaming Load:** 500-560W (4K rasterization averages ~559W per Overclocking.com)
- **With DLSS:** ~477W
- **Max Sustained Draw:** 575-600W (AIB OC models like ASUS Astral OC set to 600W)
- **Peak Transient Spikes (Igor's Lab / GameGPU):**
  - 10-20ms: up to 627.5W
  - 5-10ms: up to 738.2W
  - 1-5ms: up to 823.6W
  - <1ms: up to 901.1W
- **Power Limit Range:**
  - FE: ~100% (575W), no headroom in slider
  - ASUS Astral OC/LC: 600W (104%)
  - ASUS ROG Matrix BIOS mod: 800W
  - XOC BIOS: up to 2000W theoretical
- **Max GPU Temp:** 90C (NVIDIA spec)
- **Thermal Throttle:** 83-84C (Blackwell unified threshold)
- **Typical Gaming Temp:** 68-75C
- **VRAM:** 32 GB GDDR7, 512-bit bus, ~1792 GB/s bandwidth
- **Connector:** 1x 12V-2x6 (600W max per connector spec)

### RTX 5080

- **GPU:** GB203 (Blackwell)
- **TDP/TBP:** 360W
- **Idle Power:** ~13W (FE measured by GamersNexus)
- **Typical Gaming Load:** 320-350W
- **Max Sustained Draw:** 360W (FE); AIB models up to 400-450W
- **Peak Transient Spikes:** 500W+ estimated
- **Power Limit Range:**
  - FE: ~100% (360W)
  - AIB: varies; Gigabyte Gaming OC up to 450W, Windforce OC SFF 400W
- **Max GPU Temp:** 88C (NVIDIA spec)
- **Thermal Throttle:** 83-84C
- **Typical Gaming Temp:** 60-68C
- **VRAM:** 16 GB GDDR7, 256-bit bus
- **Connector:** 1x 12V-2x6

### RTX 5070 Ti

- **GPU:** GB203 (cut-down, Blackwell)
- **TDP/TBP:** 300W
- **Idle Power:** 17-21W (varies by review and monitor config)
- **Typical Gaming Load:** 260-290W
- **Max Sustained Draw:** 300W (FE); ASUS TUF OC measured up to 348W
- **Peak Transient Spikes:** can spike to 356W+ sustained, higher transient
- **Power Limit Range:**
  - FE: 83-100% (249W-300W)
  - AIB: varies by model; some allow up to 110%
- **Max GPU Temp:** 88C (NVIDIA spec)
- **Thermal Throttle:** 83-88C
- **Typical Gaming Temp:** 60-67C
- **VRAM:** 16 GB GDDR7, 256-bit bus
- **Connector:** 1x 12V-2x6

### RTX 5070

- **GPU:** GB205 (Blackwell)
- **TDP/TBP:** 250W
- **Idle Power:** 14-17W
- **Typical Gaming Load:** 220-245W
- **Max Sustained Draw:** 250-275W (with power limit increase)
- **Power Limit Range:**
  - FE: 100-110% (250W-275W)
  - ASUS Prime: -30% to +20% (175W-300W)
  - Some models: no slider adjustment
- **Max GPU Temp:** 88C (estimated, same Blackwell spec)
- **Thermal Throttle:** 83-88C
- **Typical Gaming Temp:** 58-65C
- **VRAM:** 12 GB GDDR7, 192-bit bus
- **Connector:** 1x 12V-2x6

### RTX 5060 Ti

- **GPU:** GB206 (Blackwell)
- **TDP/TBP:** 180W
- **Idle Power:** 14-21W (varies by monitor refresh rate and config)
- **Typical Gaming Load:** 140-165W (stress tests peak around 150W)
- **Max Sustained Draw:** 180-205W (highest measured in any game per Tom's Hardware)
- **Power Limit Range:** ~100% (180W); limited overclocking headroom
- **Max GPU Temp:** ~87C (estimated from review data)
- **Thermal Throttle:** ~83C (estimated, Blackwell spec)
- **Typical Gaming Temp:** 55-65C (peak 70C under heavy load on some models)
- **VRAM:** 16 GB GDDR7 (also 8 GB variant), 128-bit bus
- **Connector:** 1x 8-pin PCIe (not 12V-2x6); some AIB models (e.g., MSI) use 16-pin 12V-2x6
- **PSU Recommendation:** 550-650W

---

## 12V-2x6 / 12VHPWR Connector Specifications

### Connector Standards

| Parameter | 12VHPWR (ATX 3.0) | 12V-2x6 (ATX 3.1) |
|-----------|-------------------|-------------------|
| **Max Rated Power** | 600W (connector) + 75W (slot) = 675W | 600W (connector) + 75W (slot) = 675W |
| **Per-Pin Current Rating** | 9.2A (with 30C T-rise) | 9.2A (with 30C T-rise) |
| **Total Current (6 power pins)** | 55.2A = 662.4W at 12V | 55.2A = 662.4W at 12V |
| **Specified Max (derated)** | 600W | 600W |
| **Safety Margin over 575W TDP** | ~14% | ~14% |
| **Marking** | H+ | H++ |
| **Power Pin Length** | Standard | +0.25mm (improved contact) |
| **Signal Pin Length** | Standard | -1.5mm (easier insertion) |
| **Transient Spec (ATX 3.1)** | N/A | Up to 200% of rated (1200W) for <1ms |

### Pin Configuration

- **12 power pins:** 6x +12V, 6x GND (arranged in 2x6 grid)
- **4 signal pins:** 2x sense pins (Sense0, Sense1) + 2x detect pins
- **Sense Pin Logic:**
  - Both open: no power delivery
  - Sense0 grounded, Sense1 open: 300W mode
  - Sense0+Sense1 shorted together (not grounded): 150W mode
  - Both grounded: 600W mode

### Known Issues with RTX 50-Series

1. **Connector melting incidents:** Reports of RTX 5090 12V-2x6 connectors melting even with ATX 3.1 certified PSUs and native cables
2. **Root causes:** High current + high-frequency switching creates parasitic inductance, capacitance, and skin effects
3. **Cable compatibility:** Cable manufacturers advise against reusing old 12VHPWR cables with RTX 50-series GPUs
4. **Slim safety margin:** The 575W TDP leaves only ~14% margin below the 662W electrical limit of the connector

---

## ASUS ROG Astral RTX 5090 LC - Custom Power Delivery

### VRM Design
- **GPU VRM:** 24-phase power delivery
- **Memory VRM:** 7-phase power delivery
- **MOSFETs:** 80A rated per phase
- **Total GPU VRM capacity:** 24 x 80A = 1920A theoretical (well above stock needs)

### Power Configuration
- **Default TDP:** 575W
- **OC Edition Power Limit:** 600W (maximum allowed by single 12V-2x6 connector)
- **Connector:** Single 12V-2x6 (H++ rated)
- **Custom BIOS mods:** ROG Matrix 800W BIOS has been successfully flashed with PCB modifications

### ASUS Power Detector+ Feature
- Built into GPU Tweak III software
- Monitors per-pin current on the 12V-2x6 connector in real time
- **Alert threshold:** 9.2A per pin (matches ATX 3.1 spec)
- **Alert conditions:** Triggers if any pin reads 0A (poor contact) or exceeds 9.2A (overcurrent)
- Detects: poor connector contact, abnormal current draw, uneven power distribution
- Users have reported alerts triggering during heavy loads, indicating pins approaching or exceeding 9.2A

### Monitoring Implications for Power Tool
- The 9.2A per-pin threshold is the correct alarm point for 12V-2x6 connectors
- Total connector current alarm: 55.2A (all 6 power pins at 9.2A)
- Total connector power alarm: ~662W at 12V nominal
- For the Astral LC at 600W, per-pin average is 8.3A (600W / 12V / 6 pins), leaving only 0.9A margin per pin

---

## Recommended Config Defaults for Monitoring Tool

### Power Alarm Thresholds

```python
GPU_POWER_DEFAULTS = {
    "RTX 5090": {
        "tdp_watts": 575,
        "idle_watts_expected": 46,
        "idle_watts_alarm": 80,       # well above normal idle
        "load_watts_typical": 540,
        "power_warn_watts": 575,      # at TDP
        "power_alarm_watts": 625,     # above TDP, connector stress zone
        "power_critical_watts": 660,  # approaching connector max
        "transient_peak_watts": 900,  # known sub-1ms spike range
    },
    "RTX 5080": {
        "tdp_watts": 360,
        "idle_watts_expected": 13,
        "idle_watts_alarm": 40,
        "load_watts_typical": 340,
        "power_warn_watts": 360,
        "power_alarm_watts": 420,
        "power_critical_watts": 500,
        "transient_peak_watts": 550,
    },
    "RTX 5070 Ti": {
        "tdp_watts": 300,
        "idle_watts_expected": 18,
        "idle_watts_alarm": 40,
        "load_watts_typical": 275,
        "power_warn_watts": 300,
        "power_alarm_watts": 350,
        "power_critical_watts": 420,
        "transient_peak_watts": 450,
    },
    "RTX 5070": {
        "tdp_watts": 250,
        "idle_watts_expected": 15,
        "idle_watts_alarm": 35,
        "load_watts_typical": 235,
        "power_warn_watts": 250,
        "power_alarm_watts": 300,
        "power_critical_watts": 360,
        "transient_peak_watts": 380,
    },
    "RTX 5060 Ti": {
        "tdp_watts": 180,
        "idle_watts_expected": 15,
        "idle_watts_alarm": 30,
        "load_watts_typical": 155,
        "power_warn_watts": 180,
        "power_alarm_watts": 210,
        "power_critical_watts": 260,
        "transient_peak_watts": 280,
    },
}
```

### Thermal Alarm Thresholds

```python
GPU_THERMAL_DEFAULTS = {
    "RTX 5090": {
        "max_temp_spec": 90,
        "throttle_temp": 83,
        "temp_warn": 80,
        "temp_alarm": 85,
        "temp_critical": 90,
        "typical_gaming_temp": 72,
    },
    "RTX 5080": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
        "typical_gaming_temp": 65,
    },
    "RTX 5070 Ti": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
        "typical_gaming_temp": 64,
    },
    "RTX 5070": {
        "max_temp_spec": 88,
        "throttle_temp": 83,
        "temp_warn": 78,
        "temp_alarm": 83,
        "temp_critical": 88,
        "typical_gaming_temp": 62,
    },
    "RTX 5060 Ti": {
        "max_temp_spec": 87,
        "throttle_temp": 83,
        "temp_warn": 76,
        "temp_alarm": 82,
        "temp_critical": 87,
        "typical_gaming_temp": 60,
    },
}
```

### Connector Current Alarm Thresholds

```python
CONNECTOR_12V_2X6_DEFAULTS = {
    "per_pin_current_max_amps": 9.2,     # ATX 3.1 spec, 30C T-rise
    "per_pin_current_warn_amps": 8.0,    # ~87% of max
    "per_pin_current_alarm_amps": 9.2,   # at spec limit
    "total_power_pins": 6,
    "total_current_max_amps": 55.2,      # 6 * 9.2A
    "connector_max_watts": 662,          # 55.2A * 12V
    "connector_rated_watts": 600,        # derated spec
    "transient_max_watts": 1200,         # ATX 3.1: 200% for <1ms
    "connector_marking": "H++",          # 12V-2x6 marking
}

CONNECTOR_8PIN_PCIE_DEFAULTS = {
    "max_watts": 150,                    # single 8-pin spec
    "per_pin_current_max_amps": 6.25,    # 150W / 12V / 2 power pins (3 pins, but rated at 150W total)
    "total_current_max_amps": 12.5,
}
```

---

## VRAM Specifications

| Model | VRAM | Type | Bus Width | Bandwidth |
|-------|------|------|-----------|-----------|
| RTX 5090 | 32 GB | GDDR7 | 512-bit | ~1792 GB/s |
| RTX 5080 | 16 GB | GDDR7 | 256-bit | ~960 GB/s |
| RTX 5070 Ti | 16 GB | GDDR7 | 256-bit | ~896 GB/s |
| RTX 5070 | 12 GB | GDDR7 | 192-bit | ~672 GB/s |
| RTX 5060 Ti | 16 GB | GDDR7 | 128-bit | ~448 GB/s |

Note: RTX 5060 Ti also has an 8 GB variant. All 50-series use GDDR7 (not GDDR6X).

---

## Sources

- [GamersNexus RTX 5090 FE Review (idle power, thermals, gaming power)](https://gamersnexus.net/gpus/nvidia-geforce-rtx-5090-founders-edition-review-benchmarks-gaming-thermals-power)
- [GamersNexus RTX 5080 FE Review](https://gamersnexus.net/gpus/nvidia-geforce-rtx-5080-founders-edition-review-benchmarks-vs-5090-7900-xtx-4080-more)
- [Overclocking.com RTX 5090 FE Energy Review](https://en.overclocking.com/review-nvidia-rtx-5090-founders-edition/12/)
- [Igor's Lab RTX 5090 FE 600W Powerhouse Review](https://www.igorslab.de/en/nvidia-geforce-rtx-5090-founders-edition-review-the-600-watt-powerhouse-in-gaming-and-lab-tests/14/)
- [Igor's Lab RTX 5070 FE Review (idle power)](https://www.igorslab.de/en/nvidia-geforce-rtx-5070-founders-edition-test-when-the-ki-has-to-help-out/10/)
- [Igor's Lab RTX 5060 Ti 16GB Review](https://www.igorslab.de/en/nvidia-geforce-rtx-5060-ti-16-gb-in-test-economical-consumption-surprisingly-fast-but-not-with-8gb/10/)
- [GameGPU RTX 5090 Power Analysis (transient spikes up to 901W)](https://en.gamegpu.com/iron/energy-consumption-analysis-rtx-5090-power-up-to-901-vt-v-peak)
- [Tom's Hardware RTX 5060 Ti 16GB Review (power, temps)](https://www.tomshardware.com/pc-components/gpus/nvidia-geforce-rtx-5060-ti-16gb-review/9)
- [Tom's Hardware 12V-2x6 Connector Revision](https://www.tomshardware.com/news/16-pin-power-connector-gets-a-much-needed-revision-meet-the-new-12v-2x6-connector)
- [Corsair 12VHPWR vs 12V-2x6 Evolution](https://www.corsair.com/us/en/explorer/diy-builder/power-supply-units/evolving-standards-12vhpwr-and-12v-2x6/)
- [Wikipedia: 12VHPWR](https://en.wikipedia.org/wiki/12VHPWR)
- [Wikipedia: GeForce RTX 50 series](https://en.wikipedia.org/wiki/GeForce_RTX_50_series)
- [ASUS ROG Astral LC RTX 5090 OC Spec Page](https://rog.asus.com/graphics-cards/graphics-cards/rog-astral/rog-astral-lc-rtx5090-o32g-gaming/spec/)
- [ASUS Edge Up: Close Look at ROG Astral 5090](https://edgeup.asus.com/2025/a-close-look-at-the-rog-astral-geforce-rtx-5090-and-rog-astral-geforce-rtx-5080/)
- [ASUS ROG Forum: RTX 5090 Astral pins exceed 9.2A](https://rog-forum.asus.com/t5/gaming-graphics-cards/rtx-5090-asus-rog-astral-pins-exceed-9-2-amps/td-p/1119113)
- [ASUS ZenTalk: Power Detector+ Alert on ROG Astral](https://zentalk.asus.com/t5/gpus/power-detector-alert-on-rog-astral-rtx-5090-under-load/td-p/478270)
- [HWCooling: Asus Astral LC RTX 5090 OC Review](https://www.hwcooling.net/en/test-asus-astral-lc-geforce-rtx-5090-oc-ed-extrem-s-aio/)
- [ElcomSoft: RTX 5090 Power Connectors Melting](https://blog.elcomsoft.com/2025/03/nvidia-geforce-rtx-5090-power-connectors-melting-again/)
- [NotebookCheck: RTX 5090 Fire Incident](https://www.notebookcheck.net/RTX-5090-power-cable-mangled-in-fire-in-latest-troubling-incident-with-Nvidia-Blackwell-GPU.1192675.0.html)
- [Corsair: RTX 5090/5080/5070 Specs Overview](https://www.corsair.com/us/en/explorer/gamer/gaming-pcs/rtx-5090-5080-and-5070-series-gpus-everything-you-need-to-know/)
- [Corsair: Does 50-Series Need 12V-2x6 Cable](https://www.corsair.com/us/en/explorer/diy-builder/power-supply-units/does-the-50-series-need-a-12v-2x6-cable/)
- [VideoCardz: RTX 5060/5060 Ti 8-Pin Connectors](https://videocardz.com/newz/geforce-rtx-5060-5060-ti-to-feature-standard-8-pin-power-connectors-650w-psu-requirement)
- [NVIDIA RTX 5090 Product Page](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/)
- [NVIDIA RTX 5060 Ti Guide](https://www.nvidia.com/en-us/geforce/news/ultimate-guide-to-5060/)
- [Jon Gerow: About the 12V-2x6 Connector](http://jongerow.com/12V-2x6/)
- [Hardware Busters: GALAX RTX 5070 Power Analysis](https://hwbusters.com/gpu/galax-geforce-rtx-5070-1-click-oc-performance-power-analysis-noise-output/22/)
- [Hardware Busters: GALAX RTX 5070 Ti Power Analysis](https://hwbusters.com/gpu/galax-geforce-rtx-5070-ti-1-click-oc-performance-power-analysis-noise-output/22/)
- [MSI RTX 5070/5060 Ti OC Guide with Afterburner](https://www.msi.com/blog/rtx-5070-5060ti-overclocking-undervolting-guide-with-msi-afterburner-part-1)
- [TheFPSReview: RTX 5090 FE Overclocking](https://www.thefpsreview.com/2025/01/28/overclocking-nvidia-geforce-rtx-5090-founders-edition/)
