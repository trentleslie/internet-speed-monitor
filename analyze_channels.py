#!/usr/bin/env python3
"""Analyze WiFi band/channel behavior from Phase 2 data.

Compares 2.4GHz vs 5GHz performance, band switching patterns,
mesh node (BSSID) usage, and time-of-day trends.

Usage:
    python analyze_channels.py       # Generate all channel analysis plots
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data" / "phase2"
PLOTS_DIR = Path(__file__).parent / "data" / "plots" / "phase2"
CSV_FILE = DATA_DIR / "wifi_signal_tests.csv"

BAND_COLORS = {"2.4GHz": "#2196F3", "5GHz": "#FF9800"}
BAND_ORDER = ["2.4GHz", "5GHz"]


def load_data() -> pd.DataFrame:
    """Load and prepare WiFi data with band classification."""
    if not CSV_FILE.exists():
        print(f"No data file found at {CSV_FILE}")
        return pd.DataFrame()

    df = pd.read_csv(CSV_FILE)
    df = df[df["timestamp"] != "timestamp"]
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    numeric_cols = [
        "signal_pct", "channel", "ping_avg_ms", "ping_min_ms", "ping_max_ms",
        "ping_stddev_ms", "packet_loss_pct", "download_mbps", "upload_mbps",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["band"] = df["channel"].apply(
        lambda x: "2.4GHz" if x <= 14 else "5GHz" if x <= 177 else "unknown"
    )
    df["hour"] = df["timestamp"].dt.hour
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


def print_band_summary(df: pd.DataFrame):
    """Print detailed per-band statistics."""
    print("\n" + "=" * 72)
    print("CHANNEL / BAND ANALYSIS")
    print("=" * 72)

    total = len(df)
    duration = df["timestamp"].max() - df["timestamp"].min()
    print(f"\nData: {total} samples over {duration.days} days")
    print(f"Channels seen: {sorted(df['channel'].dropna().unique().astype(int))}")
    print(f"BSSIDs seen: {df['bssid'].nunique()} unique")

    for band in BAND_ORDER:
        b = df[df["band"] == band]
        if b.empty:
            continue
        pct = len(b) / total * 100
        print(f"\n{'─' * 40}")
        print(f"  {band}  ({len(b)} samples, {pct:.1f}% of total)")
        print(f"{'─' * 40}")

        channels = sorted(b["channel"].dropna().unique().astype(int))
        print(f"  Channels: {channels}")

        sig = b["signal_pct"]
        print(f"  Signal:     {sig.mean():.1f}% avg | {sig.min():.0f}%-{sig.max():.0f}% range | std {sig.std():.1f}")

        ping = b["ping_avg_ms"].dropna()
        if not ping.empty:
            print(f"  Latency:    {ping.mean():.1f} ms avg | {ping.median():.1f} ms median | {ping.max():.1f} ms max")

        loss = b["packet_loss_pct"]
        loss_events = (loss > 0).sum()
        print(f"  Pkt loss:   {loss.mean():.3f}% avg | {loss_events} events with loss")

        dl = b["download_mbps"].dropna()
        ul = b["upload_mbps"].dropna()
        if not dl.empty:
            print(f"  Download:   {dl.mean():.1f} Mbps avg | {dl.median():.1f} median | {dl.min():.1f}-{dl.max():.1f} range  (n={len(dl)})")
            print(f"  Upload:     {ul.mean():.1f} Mbps avg | {ul.median():.1f} median | {ul.min():.1f}-{ul.max():.1f} range")
        else:
            print("  Speed:      no speed test data")

    # Band switching stats. .shift() compares row 0 against NaN (always True), so
    # drop it — otherwise a single-band dataset reports 1 phantom switch.
    switches = (df["band"] != df["band"].shift()).iloc[1:].sum()
    days = max(duration.days, 1)
    print(f"\n{'─' * 40}")
    print(f"  Band Switching")
    print(f"{'─' * 40}")
    print(f"  Total switches: {switches} over {days} days ({switches / days:.1f}/day)")

    runs = []
    current_band = None
    current_count = 0
    for band in df["band"]:
        if band == current_band:
            current_count += 1
        else:
            if current_band:
                runs.append((current_band, current_count))
            current_band = band
            current_count = 1
    if current_band:
        runs.append((current_band, current_count))

    for band in BAND_ORDER:
        band_runs = [c for b, c in runs if b == band]
        if band_runs:
            s = pd.Series(band_runs)
            # Convert sample counts to approximate minutes (5-min intervals)
            print(f"  {band} runs: median {s.median():.0f} samples (~{s.median()*5:.0f} min) | "
                  f"max {s.max()} samples (~{s.max()*5} min)")

    # BSSID / mesh node analysis
    if df["bssid"].nunique() > 1:
        print(f"\n{'─' * 40}")
        print(f"  Mesh Node (BSSID) Usage")
        print(f"{'─' * 40}")
        for bssid, group in df.groupby("bssid"):
            bands = group["band"].value_counts()
            band_str = ", ".join(f"{b}: {c}" for b, c in bands.items())
            print(f"  {bssid:>10s}: {len(group)} samples ({band_str})")


def plot_band_comparison(df: pd.DataFrame):
    """Side-by-side band performance comparison."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle("2.4GHz vs 5GHz Band Comparison", fontsize=14, fontweight="bold")

    bands = [b for b in BAND_ORDER if b in df["band"].values]

    # 1. Signal strength distributions
    ax = axes[0, 0]
    data = [df[df["band"] == b]["signal_pct"].dropna() for b in bands]
    bp = ax.boxplot(data, tick_labels=bands, patch_artist=True, widths=0.5)
    for patch, band in zip(bp["boxes"], bands):
        patch.set_facecolor(BAND_COLORS[band])
        patch.set_alpha(0.7)
    ax.set_ylabel("Signal Strength (%)")
    ax.set_title("Signal Strength Distribution")
    ax.set_ylim(60, 105)
    ax.grid(True, alpha=0.3, axis="y")
    for i, b in enumerate(bands):
        n = len(data[i])
        ax.text(i + 1, 63, f"n={n}", ha="center", fontsize=9)

    # 2. Latency distributions
    ax = axes[0, 1]
    data = [df[df["band"] == b]["ping_avg_ms"].dropna() for b in bands]
    bp = ax.boxplot(data, tick_labels=bands, patch_artist=True, widths=0.5,
                    showfliers=False)  # hide outliers for readability
    for patch, band in zip(bp["boxes"], bands):
        patch.set_facecolor(BAND_COLORS[band])
        patch.set_alpha(0.7)
    ax.set_ylabel("Router Latency (ms)")
    ax.set_title("Latency Distribution (outliers hidden)")
    ax.grid(True, alpha=0.3, axis="y")
    # Show 95th percentile as annotation
    for i, b in enumerate(bands):
        p95 = data[i].quantile(0.95)
        ax.annotate(f"p95: {p95:.0f}ms", xy=(i + 1, p95),
                    fontsize=8, ha="center", va="bottom", color="red")

    # 3. Download/Upload speed comparison
    ax = axes[1, 0]
    x = np.arange(len(bands))
    width = 0.3
    dl_means = [df[(df["band"] == b)]["download_mbps"].dropna().mean() for b in bands]
    ul_means = [df[(df["band"] == b)]["upload_mbps"].dropna().mean() for b in bands]
    dl_stds = [df[(df["band"] == b)]["download_mbps"].dropna().std() for b in bands]
    ul_stds = [df[(df["band"] == b)]["upload_mbps"].dropna().std() for b in bands]

    bars1 = ax.bar(x - width/2, dl_means, width, yerr=dl_stds, label="Download",
                   color="steelblue", edgecolor="black", alpha=0.8, capsize=4)
    bars2 = ax.bar(x + width/2, ul_means, width, yerr=ul_stds, label="Upload",
                   color="coral", edgecolor="black", alpha=0.8, capsize=4)
    ax.set_ylabel("Speed (Mbps)")
    ax.set_title("Speed Test Results by Band")
    ax.set_xticks(x)
    ax.set_xticklabels(bands)
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")

    for i, b in enumerate(bands):
        n = df[(df["band"] == b)]["download_mbps"].notna().sum()
        ax.text(i, 5, f"n={n}", ha="center", fontsize=9, fontweight="bold")

    # 4. Band usage over time of day
    ax = axes[1, 1]
    hourly_5g = df.groupby("hour")["band"].apply(
        lambda x: (x == "5GHz").mean() * 100
    )
    ax.bar(hourly_5g.index, hourly_5g.values, color=BAND_COLORS["5GHz"],
           edgecolor="black", alpha=0.7, label="5GHz")
    ax.bar(hourly_5g.index, 100 - hourly_5g.values, bottom=hourly_5g.values,
           color=BAND_COLORS["2.4GHz"], edgecolor="black", alpha=0.7, label="2.4GHz")
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("% of Samples")
    ax.set_title("Band Selection by Hour")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 3)])
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "band_comparison.png", dpi=150)
    plt.show()
    print(f"Saved: {PLOTS_DIR / 'band_comparison.png'}")


def plot_band_timeline(df: pd.DataFrame):
    """Time series showing band switches overlaid with signal/latency."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    fig.suptitle("Band Behavior Over Time", fontsize=14, fontweight="bold")

    # Color each point by band
    for band in BAND_ORDER:
        mask = df["band"] == band
        b = df[mask]

        # 1. Signal
        axes[0].scatter(b["timestamp"], b["signal_pct"], s=3, alpha=0.5,
                        color=BAND_COLORS[band], label=band)

        # 2. Latency
        axes[1].scatter(b["timestamp"], b["ping_avg_ms"], s=3, alpha=0.5,
                        color=BAND_COLORS[band], label=band)

        # 3. Download speed (where available)
        dl = b.dropna(subset=["download_mbps"])
        if not dl.empty:
            axes[2].scatter(dl["timestamp"], dl["download_mbps"], s=15, alpha=0.7,
                            color=BAND_COLORS[band], label=band, edgecolors="black",
                            linewidths=0.3)

    axes[0].set_ylabel("Signal (%)")
    axes[0].set_ylim(60, 105)
    axes[0].set_title("Signal Strength")
    axes[0].legend(markerscale=3, fontsize=9)
    axes[0].grid(True, alpha=0.3)

    axes[1].set_ylabel("Latency (ms)")
    axes[1].set_title("Router Latency")
    axes[1].legend(markerscale=3, fontsize=9)
    axes[1].grid(True, alpha=0.3)

    axes[2].set_ylabel("Download (Mbps)")
    axes[2].set_title("Download Speed")
    axes[2].axhline(y=25, linestyle="--", color="red", alpha=0.4, label="4K threshold")
    axes[2].legend(markerscale=1.5, fontsize=9)
    axes[2].grid(True, alpha=0.3)

    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[2].xaxis.set_major_locator(mdates.DayLocator())
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "band_timeline.png", dpi=150)
    plt.show()
    print(f"Saved: {PLOTS_DIR / 'band_timeline.png'}")


def plot_switching_pattern(df: pd.DataFrame):
    """Visualize band switching frequency and run lengths."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Band Switching Patterns", fontsize=14, fontweight="bold")

    # Calculate run lengths
    runs = []
    current_band = None
    current_count = 0
    current_start = None
    for _, row in df.iterrows():
        if row["band"] == current_band:
            current_count += 1
        else:
            if current_band:
                runs.append({
                    "band": current_band,
                    "samples": current_count,
                    "minutes": current_count * 5,
                    "start": current_start,
                })
            current_band = row["band"]
            current_count = 1
            current_start = row["timestamp"]
    if current_band:
        runs.append({
            "band": current_band,
            "samples": current_count,
            "minutes": current_count * 5,
            "start": current_start,
        })
    runs_df = pd.DataFrame(runs)

    # 1. Run length distribution
    ax = axes[0]
    for band in BAND_ORDER:
        band_runs = runs_df[runs_df["band"] == band]["minutes"]
        if not band_runs.empty:
            bins = range(0, int(band_runs.max()) + 10, 5)
            ax.hist(band_runs, bins=bins, alpha=0.6, color=BAND_COLORS[band],
                    label=f"{band} (n={len(band_runs)} runs)", edgecolor="black")
    ax.set_xlabel("Run Duration (minutes)")
    ax.set_ylabel("Count")
    ax.set_title("How Long Does Each Band Stay Connected?")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")

    # 2. Switches per day
    ax = axes[1]
    df_copy = df.copy()
    df_copy["date"] = df_copy["timestamp"].dt.date
    df_copy["switched"] = df_copy["band"] != df_copy["band"].shift()
    df_copy.loc[df_copy.index[0], "switched"] = False  # row 0 vs NaN is a false positive
    daily_switches = df_copy.groupby("date")["switched"].sum()

    ax.bar(range(len(daily_switches)), daily_switches.values,
           color="#7E57C2", edgecolor="black", alpha=0.7)
    ax.set_xlabel("Day")
    ax.set_ylabel("Band Switches")
    ax.set_title("Band Switches Per Day")
    ax.set_xticks(range(len(daily_switches)))
    ax.set_xticklabels([d.strftime("%m-%d") for d in daily_switches.index],
                       rotation=45, ha="right", fontsize=8)
    ax.grid(True, alpha=0.3, axis="y")

    mean_switches = daily_switches.mean()
    ax.axhline(y=mean_switches, linestyle="--", color="red", alpha=0.5,
               label=f"avg: {mean_switches:.0f}/day")
    ax.legend()

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "band_switching.png", dpi=150)
    plt.show()
    print(f"Saved: {PLOTS_DIR / 'band_switching.png'}")


def main():
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()
    if df.empty:
        return

    print(f"Loaded {len(df)} records")

    # Per-location analysis (supports future multi-location data)
    locations = df["location"].unique()
    for loc in locations:
        loc_df = df[df["location"] == loc].copy()
        print(f"\n{'=' * 72}")
        print(f"  Location: {loc.replace('_', ' ').upper()}")
        print_band_summary(loc_df)

    # Plots use all data (color-coded by band)
    plot_band_comparison(df)
    plot_band_timeline(df)
    plot_switching_pattern(df)


if __name__ == "__main__":
    main()
