# Internet Speed Monitor

A comprehensive monitoring system for evaluating ISP performance and WiFi signal quality, designed to support optimal placement decisions for streaming applications.

## Project Phases

### Phase 1: ISP Comparison ✓ Complete
**March 8 - April 8, 2026**

Compared Astound Broadband (cable) vs T-Mobile 5G Home Internet using dual-interface monitoring on a Raspberry Pi.

**Key Finding:** Astound (post-cable repair) delivers ~940 Mbps download with stable 12ms latency, making it the recommended primary ISP for streaming.

📄 **[Full Report: Phase 1 ISP Comparison](reports/phase1_isp_comparison.md)**

### Phase 2: WiFi Location Testing 🔄 In Progress
**Started April 8, 2026**

Testing WiFi signal quality at different house locations to find optimal Raspberry Pi placement for a streaming webcam project.

**Current Status:** Dining room baseline established (excellent 97-100% signal, <7ms latency).

📄 **[Full Report: Phase 2 WiFi Testing](reports/phase2_wifi_testing.md)**

---

## Quick Start

### Prerequisites

```bash
# Install dependencies
uv sync

# For speed tests, install Ookla CLI
# See: https://www.speedtest.net/apps/cli
```

### Running Scripts

```bash
# Phase 1: ISP Speed Analysis
python analyze_isp.py              # Generate ISP comparison plots

# Phase 2: WiFi Testing
python wifi_test.py --help         # View WiFi test options
python wifi_test.py --set-location dining_room  # Set test location
python wifi_test.py                # Run single test
python wifi_test.py -qs            # Quick test (signal/ping only, quiet)
python analyze_wifi.py             # Generate WiFi location comparison
```

### Automated Monitoring (cron)

```bash
# WiFi signal/ping every 5 minutes
*/5 * * * * cd ~/internet-speed-monitor && python wifi_test.py -qs

# WiFi with speed test every 30 minutes
*/30 * * * * cd ~/internet-speed-monitor && python wifi_test.py -q

# ISP speed tests (Phase 1 - if running dual ISP)
*/15 * * * * cd ~/internet-speed-monitor && python speedtest_monitor.py
```

---

## Directory Structure

```
internet-speed-monitor/
├── README.md                    # This file
├── pyproject.toml               # Python project config
├── uv.lock                      # Dependency lock file
│
├── speedtest_monitor.py         # ISP speed test collection
├── connectivity_check.py        # ISP connectivity monitoring
├── wifi_test.py                 # WiFi signal quality testing
├── analyze_isp.py               # Phase 1 ISP analysis
├── analyze_wifi.py              # Phase 2 WiFi analysis
│
├── reports/                     # Stakeholder reports
│   ├── phase1_isp_comparison.md
│   └── phase2_wifi_testing.md
│
└── data/
    ├── phase1/                  # ISP comparison data
    │   ├── speed_logs_astound.csv
    │   ├── speed_logs_tmobile.csv
    │   ├── connectivity_astound.csv
    │   └── connectivity_tmobile.csv
    │
    ├── phase2/                  # WiFi testing data
    │   ├── wifi_signal_tests.csv
    │   └── wifi_test_config.json
    │
    └── plots/
        ├── phase1/              # ISP comparison visualizations
        └── phase2/              # WiFi location visualizations
```

---

## Key Metrics

### Streaming Requirements
| Quality | Upload Requirement |
|---------|-------------------|
| 720p    | ≥3 Mbps          |
| 1080p   | ≥6 Mbps          |
| 4K      | ≥25 Mbps         |

### WiFi Quality Thresholds
| Metric | Excellent | Good | Fair | Poor |
|--------|-----------|------|------|------|
| Signal | ≥80%     | 60-79% | 40-59% | <40% |
| Latency | <5ms    | 5-20ms | 20-50ms | >50ms |

---

## Hardware Setup

- **Device:** Raspberry Pi 4
- **Phase 1:** Dual Ethernet (eth0: Astound, eth1: T-Mobile)
- **Phase 2:** WiFi (wlan0) connected to TP-Link Deco BE25 mesh

---

## License

This project is for personal use to optimize home network streaming performance.
