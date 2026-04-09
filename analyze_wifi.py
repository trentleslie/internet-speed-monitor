#!/usr/bin/env python3
"""Analyze Phase 2 WiFi signal quality data across locations.

Generates location comparison charts and summary statistics to identify
optimal Raspberry Pi placement for streaming.

Usage:
    python analyze_wifi.py       # Generate all plots and summaries
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data" / "phase2"
PLOTS_DIR = Path(__file__).parent / "data" / "plots" / "phase2"
CSV_FILE = DATA_DIR / "wifi_signal_tests.csv"


def load_wifi_data() -> pd.DataFrame:
    """Load WiFi signal test data."""
    if not CSV_FILE.exists():
        print(f"No data file found at {CSV_FILE}")
        print("Run wifi_test.py to collect data first.")
        return pd.DataFrame()

    df = pd.read_csv(CSV_FILE)

    # Remove any duplicate header rows
    df = df[df["timestamp"] != "timestamp"]

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Convert numeric columns
    numeric_cols = [
        "signal_pct", "ping_avg_ms", "ping_min_ms", "ping_max_ms",
        "ping_stddev_ms", "packet_loss_pct", "download_mbps", "upload_mbps"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def location_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Generate summary statistics per location."""
    if df.empty:
        return pd.DataFrame()

    # Group by location
    summary = df.groupby("location").agg({
        "signal_pct": ["mean", "min", "max", "std", "count"],
        "ping_avg_ms": ["mean", "min", "max", "std"],
        "packet_loss_pct": ["mean", "max"],
        "download_mbps": ["mean", "count"],
        "upload_mbps": ["mean"],
    }).round(2)

    # Flatten column names
    summary.columns = ["_".join(col).strip() for col in summary.columns.values]

    return summary


def plot_location_comparison(df: pd.DataFrame):
    """Create bar charts comparing metrics across locations."""
    if df.empty:
        print("No data to plot.")
        return

    locations = df["location"].unique()
    n_locations = len(locations)

    if n_locations < 1:
        print("No location data found.")
        return

    # Compute per-location stats
    stats = []
    for loc in locations:
        loc_df = df[df["location"] == loc]
        stats.append({
            "location": loc,
            "signal_mean": loc_df["signal_pct"].mean(),
            "signal_min": loc_df["signal_pct"].min(),
            "ping_mean": loc_df["ping_avg_ms"].mean(),
            "ping_max": loc_df["ping_avg_ms"].max(),
            "ping_stddev": loc_df["ping_avg_ms"].std(),
            "packet_loss": loc_df["packet_loss_pct"].mean(),
            "download_mean": loc_df["download_mbps"].dropna().mean() if loc_df["download_mbps"].notna().any() else 0,
            "upload_mean": loc_df["upload_mbps"].dropna().mean() if loc_df["upload_mbps"].notna().any() else 0,
            "n_samples": len(loc_df),
            "n_speedtests": loc_df["download_mbps"].notna().sum(),
        })

    stats_df = pd.DataFrame(stats)

    # Create 2x2 subplot figure
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    colors = plt.cm.viridis(np.linspace(0.2, 0.8, n_locations))

    # 1. Signal Strength
    ax = axes[0, 0]
    x = range(n_locations)
    bars = ax.bar(x, stats_df["signal_mean"], color=colors, edgecolor="black", alpha=0.8)
    ax.errorbar(x, stats_df["signal_mean"],
                yerr=stats_df["signal_mean"] - stats_df["signal_min"],
                fmt="none", color="black", capsize=5)
    ax.set_ylabel("Signal Strength (%)")
    ax.set_title("WiFi Signal Strength by Location")
    ax.set_xticks(x)
    ax.set_xticklabels(stats_df["location"], rotation=45, ha="right")
    ax.set_ylim(0, 105)
    ax.axhline(y=80, linestyle="--", color="green", alpha=0.5, label="Excellent (80%+)")
    ax.axhline(y=60, linestyle="--", color="orange", alpha=0.5, label="Good (60%+)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    # Add sample counts
    for i, bar in enumerate(bars):
        ax.text(bar.get_x() + bar.get_width()/2, 5, f"n={stats_df.iloc[i]['n_samples']}",
                ha="center", va="bottom", fontsize=9, color="white", fontweight="bold")

    # 2. Router Latency
    ax = axes[0, 1]
    bars = ax.bar(x, stats_df["ping_mean"], color=colors, edgecolor="black", alpha=0.8)
    ax.errorbar(x, stats_df["ping_mean"],
                yerr=[np.zeros(n_locations), stats_df["ping_max"] - stats_df["ping_mean"]],
                fmt="none", color="black", capsize=5)
    ax.set_ylabel("Router Latency (ms)")
    ax.set_title("Ping to Router by Location")
    ax.set_xticks(x)
    ax.set_xticklabels(stats_df["location"], rotation=45, ha="right")
    ax.axhline(y=5, linestyle="--", color="green", alpha=0.5, label="Excellent (<5ms)")
    ax.axhline(y=20, linestyle="--", color="orange", alpha=0.5, label="Good (<20ms)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    # 3. Speed Tests (if available)
    ax = axes[1, 0]
    width = 0.35
    x_arr = np.array(x)

    if stats_df["download_mean"].sum() > 0:
        ax.bar(x_arr - width/2, stats_df["download_mean"], width, label="Download",
               color="steelblue", edgecolor="black", alpha=0.8)
        ax.bar(x_arr + width/2, stats_df["upload_mean"], width, label="Upload",
               color="coral", edgecolor="black", alpha=0.8)
        ax.set_ylabel("Speed (Mbps)")
        ax.set_title("Speed Test Results by Location")
        ax.legend()

        # Add speed test counts
        for i, x_pos in enumerate(x):
            n_tests = stats_df.iloc[i]["n_speedtests"]
            if n_tests > 0:
                ax.text(x_pos, 2, f"n={int(n_tests)}", ha="center", va="bottom",
                        fontsize=8, fontweight="bold")
    else:
        ax.text(0.5, 0.5, "No speed test data available\n(use wifi_test.py without --skip-speedtest)",
                ha="center", va="center", transform=ax.transAxes, fontsize=11)
        ax.set_title("Speed Test Results by Location")

    ax.set_xticks(x)
    ax.set_xticklabels(stats_df["location"], rotation=45, ha="right")
    ax.grid(True, alpha=0.3, axis="y")

    # 4. Quality Score (composite)
    ax = axes[1, 1]

    # Calculate composite score (0-100):
    # - Signal: 50% weight
    # - Latency: 30% weight (inverted, lower is better)
    # - Packet loss: 20% weight (inverted)
    scores = []
    for _, row in stats_df.iterrows():
        signal_score = row["signal_mean"]
        latency_score = max(0, 100 - (row["ping_mean"] * 2))  # 50ms = 0
        loss_score = 100 - (row["packet_loss"] * 10)  # 10% loss = 0

        composite = (signal_score * 0.5) + (latency_score * 0.3) + (loss_score * 0.2)
        scores.append(min(100, max(0, composite)))

    stats_df["quality_score"] = scores

    bars = ax.bar(x, stats_df["quality_score"], color=colors, edgecolor="black", alpha=0.8)
    ax.set_ylabel("Quality Score (0-100)")
    ax.set_title("Overall WiFi Quality Score by Location")
    ax.set_xticks(x)
    ax.set_xticklabels(stats_df["location"], rotation=45, ha="right")
    ax.set_ylim(0, 105)
    ax.axhline(y=80, linestyle="--", color="green", alpha=0.5, label="Excellent")
    ax.axhline(y=60, linestyle="--", color="orange", alpha=0.5, label="Good")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    # Add score labels
    for i, bar in enumerate(bars):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{stats_df.iloc[i]['quality_score']:.0f}",
                ha="center", va="bottom", fontsize=10, fontweight="bold")

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "location_comparison.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'location_comparison.png'}")


def plot_time_series(df: pd.DataFrame):
    """Plot signal strength and latency over time per location."""
    if df.empty:
        return

    locations = df["location"].unique()
    n_locations = len(locations)

    fig, axes = plt.subplots(n_locations, 2, figsize=(14, 4 * n_locations), squeeze=False)

    colors = plt.cm.tab10.colors

    for idx, loc in enumerate(locations):
        loc_df = df[df["location"] == loc].sort_values("timestamp")

        # Signal over time
        ax = axes[idx, 0]
        ax.plot(loc_df["timestamp"], loc_df["signal_pct"],
                marker=".", markersize=3, linewidth=0.5,
                color=colors[idx % len(colors)], alpha=0.7)
        ax.set_ylabel("Signal (%)")
        ax.set_title(f"{loc.replace('_', ' ').title()} - Signal Strength")
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)

        # Latency over time
        ax = axes[idx, 1]
        ax.plot(loc_df["timestamp"], loc_df["ping_avg_ms"],
                marker=".", markersize=3, linewidth=0.5,
                color=colors[idx % len(colors)], alpha=0.7)
        ax.set_ylabel("Latency (ms)")
        ax.set_title(f"{loc.replace('_', ' ').title()} - Router Latency")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "time_series_by_location.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'time_series_by_location.png'}")


def print_summary_table(df: pd.DataFrame):
    """Print a formatted summary table of all locations."""
    if df.empty:
        print("No data available.")
        return

    print("\n" + "=" * 80)
    print("WIFI LOCATION COMPARISON SUMMARY")
    print("=" * 80)

    locations = df["location"].unique()

    for loc in locations:
        loc_df = df[df["location"] == loc]
        n_total = len(loc_df)
        n_speed = loc_df["download_mbps"].notna().sum()

        print(f"\n--- {loc.replace('_', ' ').upper()} ---")
        print(f"Samples: {n_total} signal/ping tests, {n_speed} speed tests")

        # Time range
        start = loc_df["timestamp"].min()
        end = loc_df["timestamp"].max()
        duration = end - start
        print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')}")
        print(f"Duration: {duration}")

        # Signal
        sig = loc_df["signal_pct"]
        print(f"\nSignal Strength:")
        print(f"  Mean: {sig.mean():.1f}%  |  Range: {sig.min():.0f}% - {sig.max():.0f}%")

        # Latency
        ping = loc_df["ping_avg_ms"]
        print(f"\nRouter Latency:")
        print(f"  Mean: {ping.mean():.2f} ms  |  Max: {ping.max():.2f} ms  |  Std: {ping.std():.2f} ms")

        # Packet loss
        loss = loc_df["packet_loss_pct"]
        print(f"\nPacket Loss: {loss.mean():.2f}% average, {loss.max():.1f}% max")

        # Speed tests (if available)
        if n_speed > 0:
            dl = loc_df["download_mbps"].dropna()
            ul = loc_df["upload_mbps"].dropna()
            print(f"\nSpeed Tests:")
            print(f"  Download: {dl.mean():.1f} Mbps avg  |  Range: {dl.min():.1f} - {dl.max():.1f}")
            print(f"  Upload:   {ul.mean():.1f} Mbps avg  |  Range: {ul.min():.1f} - {ul.max():.1f}")

        # Quality assessment
        print("\nQuality Assessment:")
        if sig.mean() >= 80:
            print("  Signal: EXCELLENT (80%+)")
        elif sig.mean() >= 60:
            print("  Signal: GOOD (60-79%)")
        elif sig.mean() >= 40:
            print("  Signal: FAIR (40-59%)")
        else:
            print("  Signal: POOR (<40%)")

        if ping.mean() < 5:
            print("  Latency: EXCELLENT (<5 ms)")
        elif ping.mean() < 20:
            print("  Latency: GOOD (5-20 ms)")
        elif ping.mean() < 50:
            print("  Latency: FAIR (20-50 ms)")
        else:
            print("  Latency: POOR (>50 ms)")

    # Recommendation
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    if len(locations) == 1:
        print(f"\nOnly one location tested ({locations[0]}). Test more locations for comparison.")
    else:
        # Find best location by composite score
        best_loc = None
        best_score = -1

        for loc in locations:
            loc_df = df[df["location"] == loc]
            signal_score = loc_df["signal_pct"].mean()
            latency_score = max(0, 100 - (loc_df["ping_avg_ms"].mean() * 2))
            loss_score = 100 - (loc_df["packet_loss_pct"].mean() * 10)
            composite = (signal_score * 0.5) + (latency_score * 0.3) + (loss_score * 0.2)

            if composite > best_score:
                best_score = composite
                best_loc = loc

        print(f"\nBest location: {best_loc.replace('_', ' ').upper()}")
        print(f"Quality score: {best_score:.1f}/100")


def main():
    """Run WiFi analysis."""
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_wifi_data()

    if df.empty:
        return

    print(f"Loaded {len(df)} WiFi test records")
    print(f"Locations: {', '.join(df['location'].unique())}")

    # Generate summary and plots
    print_summary_table(df)
    plot_location_comparison(df)
    plot_time_series(df)


if __name__ == "__main__":
    main()
