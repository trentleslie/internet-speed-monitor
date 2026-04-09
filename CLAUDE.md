# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Network performance monitoring system running on a Raspberry Pi, designed in two phases:
- **Phase 1** (Complete): ISP comparison between Astound Broadband and T-Mobile 5G using dual Ethernet interfaces
- **Phase 2** (Active): WiFi signal quality testing across house locations to optimize streaming device placement

## Commands

```bash
# Install dependencies
uv sync

# Phase 1: ISP Analysis
python analyze_isp.py              # Generate ISP comparison plots (requires data in data/phase1/)

# Phase 2: WiFi Location Testing
python wifi_test.py --set-location <name>  # Configure location for automated monitoring
python wifi_test.py                         # Run full test (signal + ping + speedtest)
python wifi_test.py -qs                     # Quick test for cron (signal + ping only)
python analyze_wifi.py                      # Generate WiFi location comparison plots

# Data Collection (typically run via cron on Raspberry Pi)
python speedtest_monitor.py --interface eth0 --isp astound   # Phase 1: ISP speed test
python connectivity_check.py --interface eth0 --isp astound  # Phase 1: Connectivity ping
```

## Architecture

### Data Collection Scripts
All scripts use subprocess calls to external tools and append results to CSV files:
- `speedtest_monitor.py` - Wraps Ookla CLI (`speedtest`) with interface binding for dual-ISP testing
- `connectivity_check.py` - Pings DNS servers (8.8.8.8, 1.1.1.1) with interface binding
- `wifi_test.py` - Combines `nmcli` for signal strength, `ping` for router latency, `speedtest` for throughput

### Analysis Scripts
Both analysis scripts follow the same pattern: load CSV data with pandas, generate matplotlib/seaborn visualizations, save to `data/plots/`:
- `analyze_isp.py` - Multi-ISP comparison with streaming viability metrics, IQR-based outlier filtering, time-of-day analysis
- `analyze_wifi.py` - Location comparison with composite quality scoring (signal 50%, latency 30%, packet loss 20%)

### Data Organization
```
data/
├── phase1/          # ISP comparison: speed_logs_*.csv, connectivity_*.csv
├── phase2/          # WiFi testing: wifi_signal_tests.csv, wifi_test_config.json
└── plots/           # Generated visualizations by phase
```

### Key Constants
- `ROUTER_IP = "192.168.68.1"` - Deco mesh router for latency testing
- `CABLE_CUTOFF = "2026-03-19 14:00:00"` - Phase 1 event marker (Astound cable replacement)
- Streaming thresholds: 720p=3Mbps, 1080p=6Mbps, 4K=25Mbps upload

### External Dependencies
- **Ookla Speedtest CLI** - Must be installed separately (`speedtest --version`)
- **nmcli** - NetworkManager CLI for WiFi signal info (Linux only)
