#!/usr/bin/env python3
"""Visualize Phase 1 ISP comparison speed test and connectivity data.

Supports multi-ISP comparison with side-by-side plots and streaming viability metrics.

Usage:
    python analyze_isp.py       # Generate all plots and summaries
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from scipy import stats  # For chi-square test

DATA_DIR = Path(__file__).parent / "data" / "phase1"
PLOTS_DIR = Path(__file__).parent / "data" / "plots" / "phase1"

# Cable replacement cutoff (March 19, 2026 at 2pm PDT)
# PDT is UTC-7, so 2pm PDT = 21:00 UTC
CABLE_CUTOFF = pd.Timestamp("2026-03-19 14:00:00", tz="America/Los_Angeles")

# Minimum upload speed recommendations for streaming
STREAMING_THRESHOLDS = {
    "720p": 3,
    "1080p": 6,
    "4K": 25,
}

# Outlier detection settings
OUTLIER_IQR_MULTIPLIER = 1.5  # Standard IQR method


def get_iqr_bounds(series: pd.Series, iqr_mult: float = OUTLIER_IQR_MULTIPLIER) -> tuple[float, float, float, float]:
    """Calculate IQR bounds for outlier detection.

    Returns:
        Tuple of (q1, q3, lower_bound, upper_bound).
        Returns (nan, nan, nan, nan) if fewer than 4 data points.
    """
    if len(series) < 4:
        return (float("nan"),) * 4
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - iqr_mult * iqr
    upper = q3 + iqr_mult * iqr
    return q1, q3, lower, upper


def filter_outliers(series: pd.Series, iqr_mult: float = OUTLIER_IQR_MULTIPLIER) -> pd.Series:
    """Return boolean mask where True = valid (non-outlier) values using IQR method.

    Returns all True if fewer than 4 data points (insufficient for IQR calculation).
    """
    if len(series) < 4:
        return pd.Series(True, index=series.index)
    _, _, lower, upper = get_iqr_bounds(series, iqr_mult)
    return (series >= lower) & (series <= upper)


def load_speed_data() -> dict[str, pd.DataFrame]:
    """Load all speed_logs_*.csv files into a dict keyed by ISP name."""
    data = {}
    for csv_file in DATA_DIR.glob("speed_logs_*.csv"):
        isp = csv_file.stem.replace("speed_logs_", "")
        df = pd.read_csv(csv_file)
        # Remove duplicate header rows that may have been appended
        df = df[df["timestamp"] != "timestamp"]
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        # Convert numeric columns
        for col in ["download_mbps", "upload_mbps", "ping_ms", "jitter_ms"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.set_index("timestamp", inplace=True)
        data[isp] = df
    return data


def load_connectivity_data() -> dict[str, pd.DataFrame]:
    """Load all connectivity_*.csv files into a dict keyed by ISP name."""
    data = {}
    for csv_file in DATA_DIR.glob("connectivity_*.csv"):
        isp = csv_file.stem.replace("connectivity_", "")
        df = pd.read_csv(csv_file)
        # Remove duplicate header rows that may have been appended
        df = df[df["timestamp"] != "timestamp"]
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        # Convert numeric columns
        if "latency_ms" in df.columns:
            df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
        if "success" in df.columns:
            df["success"] = df["success"].astype(str).str.lower() == "true"
        data[isp] = df
    return data


def plot_speed_comparison(speed_data: dict[str, pd.DataFrame]):
    """Plot download/upload speeds for all ISPs on same axes."""
    if not speed_data:
        print("No speed data found. Run speedtest_monitor.py first.")
        return

    n_isps = len(speed_data)
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    colors = plt.cm.tab10.colors

    # Download comparison (with outlier filtering)
    for idx, (isp, df) in enumerate(speed_data.items()):
        valid_mask = filter_outliers(df["download_mbps"])
        df_clean = df[valid_mask]
        n_outliers = (~valid_mask).sum()
        label = f"{isp}" + (f" ({n_outliers} outliers hidden)" if n_outliers > 0 else "")
        axes[0].plot(df_clean.index, df_clean["download_mbps"],
                     marker="o", markersize=3, label=label,
                     color=colors[idx % len(colors)], alpha=0.7)
    axes[0].set_ylabel("Download (Mbps)")
    axes[0].set_title("Download Speed Comparison")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Upload comparison with streaming thresholds
    for idx, (isp, df) in enumerate(speed_data.items()):
        axes[1].plot(df.index, df["upload_mbps"],
                     marker="o", markersize=3, label=isp,
                     color=colors[idx % len(colors)], alpha=0.7)
    # Add streaming threshold lines
    for quality, threshold in STREAMING_THRESHOLDS.items():
        axes[1].axhline(y=threshold, linestyle="--", alpha=0.5,
                        label=f"{quality} minimum ({threshold} Mbps)")
    axes[1].set_ylabel("Upload (Mbps)")
    axes[1].set_title("Upload Speed Comparison (with streaming thresholds)")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, alpha=0.3)

    # Ping comparison
    for idx, (isp, df) in enumerate(speed_data.items()):
        axes[2].plot(df.index, df["ping_ms"],
                     marker="o", markersize=3, label=isp,
                     color=colors[idx % len(colors)], alpha=0.7)
    axes[2].set_ylabel("Ping (ms)")
    axes[2].set_xlabel("Time")
    axes[2].set_title("Latency Comparison")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "speed_comparison.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'speed_comparison.png'}")


def plot_connectivity_comparison(conn_data: dict[str, pd.DataFrame]):
    """Plot connectivity latency for all ISPs."""
    if not conn_data:
        print("No connectivity data found. Run connectivity_check.py first.")
        return

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = plt.cm.tab10.colors

    for idx, (isp, df) in enumerate(conn_data.items()):
        # Pivot to get average latency across targets per timestamp
        df_avg = df.groupby("timestamp")["latency_ms"].mean()
        ax.plot(df_avg.index, df_avg.values,
                marker=".", markersize=2, linewidth=0.5,
                label=isp, color=colors[idx % len(colors)], alpha=0.7)

    ax.set_ylabel("Avg Latency (ms)")
    ax.set_xlabel("Time")
    ax.set_title("Connectivity Check Latency by ISP")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "connectivity_comparison.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'connectivity_comparison.png'}")


def plot_time_of_day(speed_data: dict[str, pd.DataFrame]):
    """Scatter plot with hour of day on x-axis to reveal daily patterns."""
    if not speed_data:
        print("No speed data yet.")
        return

    n_isps = len(speed_data)
    fig, axes = plt.subplots(n_isps, 2, figsize=(14, 4 * n_isps), squeeze=False)

    colors = plt.cm.tab10.colors

    for idx, (isp, df) in enumerate(speed_data.items()):
        df = df.reset_index()
        df["hour"] = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60

        # Filter download outliers for plotting
        valid_mask = filter_outliers(df["download_mbps"])
        df_clean = df[valid_mask]

        # Download by time of day (outliers filtered)
        axes[idx, 0].scatter(df_clean["hour"], df_clean["download_mbps"],
                             alpha=0.4, s=15, color=colors[idx % len(colors)])
        axes[idx, 0].set_ylabel("Download (Mbps)")
        axes[idx, 0].set_title(f"{isp.upper()} - Download by Time of Day")
        axes[idx, 0].set_xlim(0, 24)
        axes[idx, 0].set_xticks(range(0, 25, 2))
        axes[idx, 0].grid(True, alpha=0.3)

        # Upload by time of day with threshold lines
        axes[idx, 1].scatter(df["hour"], df["upload_mbps"],
                             alpha=0.4, s=15, color=colors[idx % len(colors)])
        for quality, threshold in STREAMING_THRESHOLDS.items():
            axes[idx, 1].axhline(y=threshold, linestyle="--", alpha=0.4)
        axes[idx, 1].set_ylabel("Upload (Mbps)")
        axes[idx, 1].set_title(f"{isp.upper()} - Upload by Time of Day")
        axes[idx, 1].set_xlim(0, 24)
        axes[idx, 1].set_xticks(range(0, 25, 2))
        axes[idx, 1].grid(True, alpha=0.3)

    # Add x-axis label to bottom row only
    for ax in axes[-1]:
        ax.set_xlabel("Hour of Day")

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "time_of_day_comparison.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'time_of_day_comparison.png'}")


def upload_consistency_metrics(speed_data: dict[str, pd.DataFrame]) -> dict:
    """Calculate upload consistency metrics critical for live streaming.

    Returns dict with per-ISP metrics:
    - mean, std, cv (coefficient of variation)
    - p10, p25 (percentiles - worst-case scenarios)
    - streaming_viable (dict of quality levels and % of time viable)
    """
    metrics = {}

    for isp, df in speed_data.items():
        upload = df["upload_mbps"]
        m = {
            "mean": upload.mean(),
            "std": upload.std(),
            "cv": upload.std() / upload.mean() if upload.mean() > 0 else float("inf"),
            "min": upload.min(),
            "max": upload.max(),
            "p10": upload.quantile(0.10),
            "p25": upload.quantile(0.25),
            "p50": upload.quantile(0.50),
            "streaming_viable": {},
        }
        # Calculate % of tests that meet each streaming threshold
        for quality, threshold in STREAMING_THRESHOLDS.items():
            viable_pct = (upload >= threshold).mean() * 100
            m["streaming_viable"][quality] = viable_pct

        metrics[isp] = m

    return metrics


def analyze_outliers(speed_data: dict[str, pd.DataFrame]) -> dict:
    """Characterize download speed outliers for each ISP.

    Returns dict with per-ISP outlier analysis:
    - count, percentage of total
    - low_outliers, high_outliers (counts)
    - statistics (min, max, mean for outlier values)
    - hour_distribution (dict of hour -> count)
    - day_distribution (dict of day name -> count)
    - outlier_df (DataFrame of outlier rows for plotting)
    - full_df (DataFrame of all rows for normalized rate analysis)
    """
    results = {}

    for isp, df in speed_data.items():
        df = df.reset_index()
        # Add time columns to full dataframe for normalized analysis
        df["hour"] = df["timestamp"].dt.hour
        df["day_name"] = df["timestamp"].dt.day_name()
        download = df["download_mbps"]

        if len(download) < 4:
            results[isp] = {"count": 0, "percentage": 0, "insufficient_data": True, "full_df": df}
            continue

        q1, q3, lower, upper = get_iqr_bounds(download)
        outlier_mask = (download < lower) | (download > upper)
        outliers_df = df[outlier_mask].copy()
        n_outliers = len(outliers_df)

        if n_outliers == 0:
            results[isp] = {
                "count": 0,
                "percentage": 0,
                "bounds": {"q1": q1, "q3": q3, "lower": lower, "upper": upper},
                "full_df": df,
            }
            continue

        # Classify as low or high outliers
        low_mask = outliers_df["download_mbps"] < lower
        high_mask = outliers_df["download_mbps"] > upper

        # Time analysis (hour/day_name already added above)
        hour_dist = outliers_df["hour"].value_counts().sort_index().to_dict()
        day_dist = outliers_df["day_name"].value_counts().to_dict()

        results[isp] = {
            "count": n_outliers,
            "percentage": n_outliers / len(df) * 100,
            "low_outliers": low_mask.sum(),
            "high_outliers": high_mask.sum(),
            "bounds": {"q1": q1, "q3": q3, "lower": lower, "upper": upper},
            "stats": {
                "download": {
                    "min": outliers_df["download_mbps"].min(),
                    "max": outliers_df["download_mbps"].max(),
                    "mean": outliers_df["download_mbps"].mean(),
                },
                "upload": {
                    "min": outliers_df["upload_mbps"].min(),
                    "max": outliers_df["upload_mbps"].max(),
                    "mean": outliers_df["upload_mbps"].mean(),
                },
                "ping": {
                    "min": outliers_df["ping_ms"].min(),
                    "max": outliers_df["ping_ms"].max(),
                    "mean": outliers_df["ping_ms"].mean(),
                },
            },
            "hour_distribution": hour_dist,
            "day_distribution": day_dist,
            "outlier_df": outliers_df,
            "full_df": df,
        }

    return results


def analyze_latency_outliers(conn_data: dict[str, pd.DataFrame]) -> dict:
    """Characterize connectivity latency outliers for each ISP.

    High latency spikes are critical for streaming/gaming performance.
    """
    results = {}

    for isp, df in conn_data.items():
        df = df.copy()
        # Add time columns to full dataframe for normalized analysis
        df["hour"] = df["timestamp"].dt.hour
        df["day_name"] = df["timestamp"].dt.day_name()
        latency = df["latency_ms"].dropna()

        if len(latency) < 4:
            results[isp] = {"count": 0, "percentage": 0, "insufficient_data": True, "full_df": df}
            continue

        q1, q3, lower, upper = get_iqr_bounds(latency)
        # For latency, we mainly care about HIGH outliers (spikes)
        high_outlier_mask = df["latency_ms"] > upper
        outliers_df = df[high_outlier_mask].copy()
        n_outliers = len(outliers_df)

        if n_outliers == 0:
            results[isp] = {
                "count": 0,
                "percentage": 0,
                "bounds": {"q1": q1, "q3": q3, "upper": upper},
                "full_df": df,
            }
            continue

        # Time analysis (hour/day_name already added above)
        hour_dist = outliers_df["hour"].value_counts().sort_index().to_dict()
        day_dist = outliers_df["day_name"].value_counts().to_dict()

        results[isp] = {
            "count": n_outliers,
            "percentage": n_outliers / len(df) * 100,
            "bounds": {"q1": q1, "q3": q3, "upper": upper},
            "stats": {
                "min": outliers_df["latency_ms"].min(),
                "max": outliers_df["latency_ms"].max(),
                "mean": outliers_df["latency_ms"].mean(),
                "p50": outliers_df["latency_ms"].quantile(0.50),
                "p95": outliers_df["latency_ms"].quantile(0.95),
            },
            "hour_distribution": hour_dist,
            "day_distribution": day_dist,
            "outlier_df": outliers_df,
            "full_df": df,
        }

    return results


def compute_normalized_rates(full_df: pd.DataFrame, outlier_df: pd.DataFrame) -> dict:
    """Compute outlier rates normalized by sample count per time bucket.

    Returns:
        hour_rates: dict of hour -> (outlier_rate, outlier_count, total_count)
        day_rates: dict of day_name -> (outlier_rate, outlier_count, total_count)
    """
    # Group full_df by hour, count total samples
    hour_totals = full_df.groupby("hour").size()
    # Group outlier_df by hour, count outliers
    hour_outliers = outlier_df.groupby("hour").size() if len(outlier_df) > 0 else pd.Series(dtype=int)

    hour_rates = {}
    for hour in range(24):
        total = hour_totals.get(hour, 0)
        outliers = hour_outliers.get(hour, 0)
        rate = outliers / total if total > 0 else 0.0
        hour_rates[hour] = (rate, outliers, total)

    # Same for day-of-week
    day_totals = full_df.groupby("day_name").size()
    day_outliers = outlier_df.groupby("day_name").size() if len(outlier_df) > 0 else pd.Series(dtype=int)

    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_rates = {}
    for day in day_order:
        total = day_totals.get(day, 0)
        outliers = day_outliers.get(day, 0)
        rate = outliers / total if total > 0 else 0.0
        day_rates[day] = (rate, outliers, total)

    return {"hour_rates": hour_rates, "day_rates": day_rates}


def test_congestion_window(full_df: pd.DataFrame, outlier_df: pd.DataFrame,
                           hours: list[int], days: list[str]) -> dict:
    """Chi-square test for whether outlier rate in specified window differs from baseline.

    Args:
        full_df: DataFrame with all samples (must have 'hour' and 'day_name' columns)
        outlier_df: DataFrame with outlier samples only
        hours: List of hours (0-23) to include in congestion window
        days: List of day names (e.g., ["Thursday", "Monday"]) to include

    Returns dict with:
        window_samples, window_outliers, window_rate,
        baseline_samples, baseline_outliers, baseline_rate,
        chi2, p_value, significant (bool)
    """
    # Define window mask
    window_mask_full = full_df["hour"].isin(hours) & full_df["day_name"].isin(days)
    window_mask_outlier = outlier_df["hour"].isin(hours) & outlier_df["day_name"].isin(days) if len(outlier_df) > 0 else pd.Series(False, index=outlier_df.index)

    window_samples = window_mask_full.sum()
    window_outliers = window_mask_outlier.sum()
    baseline_samples = (~window_mask_full).sum()
    baseline_outliers = len(outlier_df) - window_outliers

    # Compute rates
    window_rate = window_outliers / window_samples if window_samples > 0 else 0.0
    baseline_rate = baseline_outliers / baseline_samples if baseline_samples > 0 else 0.0

    # Build 2x2 contingency table for chi-square test
    # Rows: Window vs Baseline
    # Cols: Outlier vs Normal
    window_normal = window_samples - window_outliers
    baseline_normal = baseline_samples - baseline_outliers

    contingency_table = [
        [window_outliers, window_normal],
        [baseline_outliers, baseline_normal],
    ]

    # Need at least some samples in each group to run test
    if window_samples < 5 or baseline_samples < 5:
        return {
            "window_samples": window_samples,
            "window_outliers": window_outliers,
            "window_rate": window_rate,
            "baseline_samples": baseline_samples,
            "baseline_outliers": baseline_outliers,
            "baseline_rate": baseline_rate,
            "chi2": None,
            "p_value": None,
            "significant": None,
            "insufficient_data": True,
        }

    # Run chi-square test
    chi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)

    return {
        "window_samples": window_samples,
        "window_outliers": window_outliers,
        "window_rate": window_rate,
        "baseline_samples": baseline_samples,
        "baseline_outliers": baseline_outliers,
        "baseline_rate": baseline_rate,
        "chi2": chi2,
        "p_value": p_value,
        "significant": p_value < 0.05,
    }


def plot_normalized_outlier_rates(speed_data: dict, conn_data: dict,
                                  speed_outliers: dict, latency_outliers: dict):
    """Plot normalized outlier rates by hour and day for each ISP."""
    colors = plt.cm.tab10.colors

    # Determine number of ISPs with outlier data
    isps_with_speed_outliers = [isp for isp, data in speed_outliers.items()
                                 if data.get("count", 0) > 0 and "full_df" in data]
    isps_with_latency_outliers = [isp for isp, data in latency_outliers.items()
                                   if data.get("count", 0) > 0 and "full_df" in data]

    if not isps_with_speed_outliers and not isps_with_latency_outliers:
        print("No outliers to plot normalized rates for.")
        return

    # Create figure with subplots: 2 columns (hour, day) × N rows (one per ISP/metric combo)
    n_rows = len(isps_with_speed_outliers) + len(isps_with_latency_outliers)
    if n_rows == 0:
        return

    fig, axes = plt.subplots(n_rows, 2, figsize=(14, 4 * n_rows), squeeze=False)

    row = 0

    # Plot speed outlier rates
    for idx, isp in enumerate(isps_with_speed_outliers):
        data = speed_outliers[isp]
        full_df = data["full_df"]
        outlier_df = data["outlier_df"]
        rates = compute_normalized_rates(full_df, outlier_df)

        color = colors[idx % len(colors)]

        # Hour-of-day plot
        ax = axes[row, 0]
        hours = list(range(24))
        hour_rates = [rates["hour_rates"][h][0] * 100 for h in hours]  # Convert to percentage
        hour_totals = [rates["hour_rates"][h][2] for h in hours]

        bars = ax.bar(hours, hour_rates, color=color, alpha=0.7, edgecolor="black")

        # Annotate bars with sample counts and highlight low-sample hours
        for i, (bar, total) in enumerate(zip(bars, hour_totals)):
            if total > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"n={total}", ha="center", va="bottom", fontsize=7, rotation=90)
            if total < 5:
                bar.set_hatch("//")  # Hatching for low-sample hours
                bar.set_alpha(0.4)

        ax.set_xlabel("Hour of Day")
        ax.set_ylabel("Outlier Rate (%)")
        ax.set_title(f"{isp.upper()} Download - Outlier Rate by Hour")
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(0, 24, 2))
        ax.grid(True, alpha=0.3, axis="y")

        # Day-of-week plot
        ax = axes[row, 1]
        day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_map = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
                   "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}
        full_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        day_rates_pct = [rates["day_rates"][d][0] * 100 for d in full_days]
        day_totals = [rates["day_rates"][d][2] for d in full_days]

        bars = ax.bar(day_order, day_rates_pct, color=color, alpha=0.7, edgecolor="black")

        for bar, total in zip(bars, day_totals):
            if total > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"n={total}", ha="center", va="bottom", fontsize=8)
            if total < 5:
                bar.set_hatch("//")
                bar.set_alpha(0.4)

        ax.set_xlabel("Day of Week")
        ax.set_ylabel("Outlier Rate (%)")
        ax.set_title(f"{isp.upper()} Download - Outlier Rate by Day")
        ax.grid(True, alpha=0.3, axis="y")

        row += 1

    # Plot latency outlier rates
    for idx, isp in enumerate(isps_with_latency_outliers):
        data = latency_outliers[isp]
        full_df = data["full_df"]
        outlier_df = data["outlier_df"]
        rates = compute_normalized_rates(full_df, outlier_df)

        color = colors[(idx + len(isps_with_speed_outliers)) % len(colors)]

        # Hour-of-day plot
        ax = axes[row, 0]
        hours = list(range(24))
        hour_rates = [rates["hour_rates"][h][0] * 100 for h in hours]
        hour_totals = [rates["hour_rates"][h][2] for h in hours]

        bars = ax.bar(hours, hour_rates, color=color, alpha=0.7, edgecolor="black")

        for i, (bar, total) in enumerate(zip(bars, hour_totals)):
            if total > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"n={total}", ha="center", va="bottom", fontsize=7, rotation=90)
            if total < 5:
                bar.set_hatch("//")
                bar.set_alpha(0.4)

        ax.set_xlabel("Hour of Day")
        ax.set_ylabel("Outlier Rate (%)")
        ax.set_title(f"{isp.upper()} Latency - Spike Rate by Hour")
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(0, 24, 2))
        ax.grid(True, alpha=0.3, axis="y")

        # Day-of-week plot
        ax = axes[row, 1]
        day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        full_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        day_rates_pct = [rates["day_rates"][d][0] * 100 for d in full_days]
        day_totals = [rates["day_rates"][d][2] for d in full_days]

        bars = ax.bar(day_order, day_rates_pct, color=color, alpha=0.7, edgecolor="black")

        for bar, total in zip(bars, day_totals):
            if total > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"n={total}", ha="center", va="bottom", fontsize=8)
            if total < 5:
                bar.set_hatch("//")
                bar.set_alpha(0.4)

        ax.set_xlabel("Day of Week")
        ax.set_ylabel("Outlier Rate (%)")
        ax.set_title(f"{isp.upper()} Latency - Spike Rate by Day")
        ax.grid(True, alpha=0.3, axis="y")

        row += 1

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "normalized_outlier_rates.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'normalized_outlier_rates.png'}")


def normalized_outlier_summary(speed_data: dict, conn_data: dict,
                               speed_outliers: dict, latency_outliers: dict):
    """Print normalized outlier rate analysis with statistical testing."""
    print("\n" + "=" * 60)
    print("NORMALIZED OUTLIER RATE VERIFICATION")
    print("=" * 60)

    # Process speed outliers
    for isp, data in speed_outliers.items():
        if data.get("count", 0) == 0 or "full_df" not in data:
            continue

        print(f"\n--- {isp.upper()} DOWNLOAD OUTLIERS ---")
        full_df = data["full_df"]
        outlier_df = data["outlier_df"]
        rates = compute_normalized_rates(full_df, outlier_df)

        # Hour-of-day rates table
        print("\nHour-of-day rates (outliers/total):")
        hour_rates_sorted = sorted(
            [(h, r[0], r[1], r[2]) for h, r in rates["hour_rates"].items() if r[2] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        for h, rate, outliers, total in hour_rates_sorted[:8]:  # Top 8
            marker = " ← PEAK" if rate == hour_rates_sorted[0][1] else ""
            print(f"  {h:02d}:00: {rate * 100:5.1f}% ({outliers}/{total}){marker}")

        # Day-of-week rates table
        print("\nDay-of-week rates:")
        day_rates_sorted = sorted(
            [(d, r[0], r[1], r[2]) for d, r in rates["day_rates"].items() if r[2] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        for day, rate, outliers, total in day_rates_sorted:
            marker = " ← PEAK" if rate == day_rates_sorted[0][1] else ""
            print(f"  {day:9s}: {rate * 100:5.1f}% ({outliers}/{total}){marker}")

        # Congestion window test for Astound
        if isp.lower() == "astound":
            print("\nCongestion window test (Thu+Mon, 14:00-17:00):")
            test_result = test_congestion_window(
                full_df, outlier_df,
                hours=[14, 15, 16, 17],
                days=["Thursday", "Monday"],
            )
            _print_congestion_test_result(test_result, isp)

        # Congestion window test for T-Mobile (weekend pattern)
        elif "tmobile" in isp.lower() or "t-mobile" in isp.lower():
            print("\nCongestion window test (Sat+Sun, all hours):")
            test_result = test_congestion_window(
                full_df, outlier_df,
                hours=list(range(24)),
                days=["Saturday", "Sunday"],
            )
            _print_congestion_test_result(test_result, isp)

    # Process latency outliers
    for isp, data in latency_outliers.items():
        if data.get("count", 0) == 0 or "full_df" not in data:
            continue

        print(f"\n--- {isp.upper()} LATENCY SPIKES ---")
        full_df = data["full_df"]
        outlier_df = data["outlier_df"]
        rates = compute_normalized_rates(full_df, outlier_df)

        # Hour-of-day rates
        print("\nHour-of-day rates (spikes/total):")
        hour_rates_sorted = sorted(
            [(h, r[0], r[1], r[2]) for h, r in rates["hour_rates"].items() if r[2] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        for h, rate, outliers, total in hour_rates_sorted[:8]:
            marker = " ← PEAK" if rate == hour_rates_sorted[0][1] else ""
            print(f"  {h:02d}:00: {rate * 100:5.1f}% ({outliers}/{total}){marker}")

        # Day-of-week rates
        print("\nDay-of-week rates:")
        day_rates_sorted = sorted(
            [(d, r[0], r[1], r[2]) for d, r in rates["day_rates"].items() if r[2] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        for day, rate, outliers, total in day_rates_sorted:
            marker = " ← PEAK" if rate == day_rates_sorted[0][1] else ""
            print(f"  {day:9s}: {rate * 100:5.1f}% ({outliers}/{total}){marker}")

        # T-Mobile weekend latency test
        if "tmobile" in isp.lower() or "t-mobile" in isp.lower():
            print("\nCongestion window test (Sat+Sun):")
            test_result = test_congestion_window(
                full_df, outlier_df,
                hours=list(range(24)),
                days=["Saturday", "Sunday"],
            )
            _print_congestion_test_result(test_result, isp, metric="latency spikes")


def _print_congestion_test_result(result: dict, isp: str, metric: str = "outliers"):
    """Helper to print chi-square test results."""
    if result.get("insufficient_data"):
        print(f"  Insufficient data for statistical test (need ≥5 samples per group)")
        return

    print(f"  Window:   {result['window_rate'] * 100:.1f}% {metric} ({result['window_outliers']}/{result['window_samples']})")
    print(f"  Baseline: {result['baseline_rate'] * 100:.1f}% {metric} ({result['baseline_outliers']}/{result['baseline_samples']})")
    print(f"  Chi-square: {result['chi2']:.2f}, p-value: {result['p_value']:.5f}")

    if result["significant"]:
        sig_level = "p<0.001" if result["p_value"] < 0.001 else (
            "p<0.01" if result["p_value"] < 0.01 else "p<0.05"
        )
        print(f"\n  ✓ CONFIRMED: {isp.upper()} {metric} are significantly time-clustered ({sig_level})")
        print(f"    This indicates node congestion, not random equipment failure.")
    else:
        print(f"\n  ✗ NOT CONFIRMED: {isp.upper()} time-clustering is NOT statistically significant")
        print(f"    Observed patterns may be sampling artifacts.")


def plot_outlier_time_of_day(speed_outliers: dict, latency_outliers: dict):
    """Scatter plot showing outliers vs hour of day, colored by ISP."""
    colors = plt.cm.tab10.colors

    # Create 2x1 subplot: speed outliers on top, latency outliers on bottom
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    # Speed outliers (download)
    ax = axes[0]
    has_speed_data = False
    for idx, (isp, data) in enumerate(speed_outliers.items()):
        if data.get("count", 0) == 0:
            continue
        has_speed_data = True
        outliers_df = data["outlier_df"]
        hour = outliers_df["timestamp"].dt.hour + outliers_df["timestamp"].dt.minute / 60

        # Color low outliers darker, high outliers lighter
        bounds = data["bounds"]
        low_mask = outliers_df["download_mbps"] < bounds["lower"]

        # Plot low outliers with 'v' marker, high with '^'
        if low_mask.any():
            ax.scatter(hour[low_mask], outliers_df.loc[low_mask, "download_mbps"],
                       alpha=0.7, s=40, color=colors[idx % len(colors)],
                       marker="v", label=f"{isp} LOW ({low_mask.sum()})")
        if (~low_mask).any():
            ax.scatter(hour[~low_mask], outliers_df.loc[~low_mask, "download_mbps"],
                       alpha=0.7, s=40, color=colors[idx % len(colors)],
                       marker="^", label=f"{isp} HIGH ({(~low_mask).sum()})")

    if has_speed_data:
        ax.set_ylabel("Download (Mbps)")
        ax.set_title("Download Speed Outliers by Time of Day")
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 2))
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
    else:
        ax.text(0.5, 0.5, "No download speed outliers", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_title("Download Speed Outliers by Time of Day")

    # Latency outliers
    ax = axes[1]
    has_latency_data = False
    for idx, (isp, data) in enumerate(latency_outliers.items()):
        if data.get("count", 0) == 0:
            continue
        has_latency_data = True
        outliers_df = data["outlier_df"]
        hour = outliers_df["timestamp"].dt.hour + outliers_df["timestamp"].dt.minute / 60

        ax.scatter(hour, outliers_df["latency_ms"],
                   alpha=0.5, s=15, color=colors[idx % len(colors)],
                   label=f"{isp} ({data['count']} spikes)")

    if has_latency_data:
        ax.set_ylabel("Latency (ms)")
        ax.set_xlabel("Hour of Day")
        ax.set_title("Connectivity Latency Spikes by Time of Day")
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 2))
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
    else:
        ax.text(0.5, 0.5, "No latency outliers", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_xlabel("Hour of Day")
        ax.set_title("Connectivity Latency Spikes by Time of Day")

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "outlier_analysis.png", dpi=150)
    plt.show()
    print(f"Saved plot to {PLOTS_DIR / 'outlier_analysis.png'}")


def outlier_summary(speed_outliers: dict, latency_outliers: dict):
    """Print detailed outlier characterization."""
    print("\n" + "=" * 60)
    print("OUTLIER ANALYSIS")
    print("=" * 60)

    # Speed outliers
    print("\n--- DOWNLOAD SPEED OUTLIERS ---")
    for isp, data in speed_outliers.items():
        print(f"\n{isp.upper()}:")
        if data.get("insufficient_data"):
            print("  Insufficient data for outlier analysis")
            continue
        if data["count"] == 0:
            print(f"  No outliers detected (bounds: {data['bounds']['lower']:.1f} - {data['bounds']['upper']:.1f} Mbps)")
            continue

        bounds = data["bounds"]
        print(f"  IQR bounds: {bounds['lower']:.1f} - {bounds['upper']:.1f} Mbps")
        print(f"  Total outliers: {data['count']} ({data['percentage']:.1f}% of tests)")
        print(f"  Low outliers (drops): {data['low_outliers']}")
        print(f"  High outliers (spikes): {data['high_outliers']}")

        stats = data["stats"]
        print(f"\n  Outlier statistics:")
        print(f"    Download: {stats['download']['min']:.1f} - {stats['download']['max']:.1f} Mbps "
              f"(avg: {stats['download']['mean']:.1f})")
        print(f"    Upload during outliers: {stats['upload']['min']:.1f} - {stats['upload']['max']:.1f} Mbps "
              f"(avg: {stats['upload']['mean']:.1f})")
        print(f"    Ping during outliers: {stats['ping']['min']:.1f} - {stats['ping']['max']:.1f} ms "
              f"(avg: {stats['ping']['mean']:.1f})")

        # Time distribution
        hour_dist = data["hour_distribution"]
        if hour_dist:
            peak_hours = sorted(hour_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"\n  Peak outlier hours: {', '.join(f'{h}:00 ({c})' for h, c in peak_hours)}")

        day_dist = data["day_distribution"]
        if day_dist and len(day_dist) > 1:
            peak_days = sorted(day_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"  Peak outlier days: {', '.join(f'{d} ({c})' for d, c in peak_days)}")

    # Latency outliers
    print("\n--- CONNECTIVITY LATENCY SPIKES ---")
    for isp, data in latency_outliers.items():
        print(f"\n{isp.upper()}:")
        if data.get("insufficient_data"):
            print("  Insufficient data for outlier analysis")
            continue
        if data["count"] == 0:
            print(f"  No latency spikes detected (threshold: >{data['bounds']['upper']:.1f} ms)")
            continue

        bounds = data["bounds"]
        print(f"  Normal range: <{bounds['upper']:.1f} ms (Q3 + 1.5×IQR)")
        print(f"  Total spikes: {data['count']} ({data['percentage']:.1f}% of checks)")

        stats = data["stats"]
        print(f"\n  Spike statistics:")
        print(f"    Range: {stats['min']:.1f} - {stats['max']:.1f} ms")
        print(f"    Mean: {stats['mean']:.1f} ms, Median: {stats['p50']:.1f} ms")
        print(f"    95th percentile: {stats['p95']:.1f} ms")

        # Time distribution
        hour_dist = data["hour_distribution"]
        if hour_dist:
            peak_hours = sorted(hour_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"\n  Peak spike hours: {', '.join(f'{h}:00 ({c})' for h, c in peak_hours)}")

        day_dist = data["day_distribution"]
        if day_dist and len(day_dist) > 1:
            peak_days = sorted(day_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"  Peak spike days: {', '.join(f'{d} ({c})' for d, c in peak_days)}")


def summary(speed_data: dict[str, pd.DataFrame], conn_data: dict[str, pd.DataFrame]):
    """Print summary statistics for all ISPs."""
    if speed_data:
        print("\n" + "=" * 60)
        print("SPEED TEST SUMMARY")
        print("=" * 60)

        for isp, df in speed_data.items():
            print(f"\n--- {isp.upper()} ---")
            print(f"Total tests: {len(df)}")

            # Filter download outliers
            valid_mask = filter_outliers(df["download_mbps"])
            n_outliers = (~valid_mask).sum()
            dl_clean = df.loc[valid_mask, "download_mbps"]

            if n_outliers > 0:
                print(f"Download: {dl_clean.mean():.1f} Mbps avg "
                      f"(min: {dl_clean.min():.1f}, max: {dl_clean.max():.1f}) "
                      f"[{n_outliers} outliers excluded]")
            else:
                print(f"Download: {dl_clean.mean():.1f} Mbps avg "
                      f"(min: {dl_clean.min():.1f}, max: {dl_clean.max():.1f})")

            print(f"Upload: {df['upload_mbps'].mean():.1f} Mbps avg "
                  f"(min: {df['upload_mbps'].min():.1f}, max: {df['upload_mbps'].max():.1f})")
            print(f"Ping: {df['ping_ms'].mean():.1f} ms avg")

        # Upload consistency analysis
        metrics = upload_consistency_metrics(speed_data)
        print("\n" + "=" * 60)
        print("UPLOAD CONSISTENCY (Critical for Streaming)")
        print("=" * 60)

        for isp, m in metrics.items():
            print(f"\n--- {isp.upper()} ---")
            print(f"Upload: {m['mean']:.1f} ± {m['std']:.1f} Mbps (CV: {m['cv']:.2%})")
            print(f"10th percentile: {m['p10']:.1f} Mbps (worst-case buffer)")
            print(f"25th percentile: {m['p25']:.1f} Mbps")
            print("Streaming viability:")
            for quality, viable_pct in m["streaming_viable"].items():
                status = "✓" if viable_pct >= 95 else "⚠" if viable_pct >= 80 else "✗"
                print(f"  {status} {quality}: {viable_pct:.1f}% of tests viable")

    if conn_data:
        print("\n" + "=" * 60)
        print("CONNECTIVITY SUMMARY")
        print("=" * 60)

        for isp, df in conn_data.items():
            success_rate = df["success"].mean() * 100
            print(f"\n--- {isp.upper()} ---")
            print(f"Total checks: {len(df)}")
            print(f"Success rate: {success_rate:.1f}%")
            if success_rate < 100:
                failures = df[~df["success"]]
                print(f"Failures: {len(failures)}")
            if df["latency_ms"].notna().any():
                print(f"Avg latency: {df['latency_ms'].mean():.1f} ms")


def plot_astound_before_after_boxplot(speed_data: dict[str, pd.DataFrame]):
    """Seaborn boxplot comparing Astound before/after cable replacement.

    Creates a 2-panel figure showing download and upload speed distributions
    for the period before and after the cable replacement on March 19, 2026 at 2pm PDT.
    """
    # Get Astound data
    astound_df = None
    for isp, df in speed_data.items():
        if "astound" in isp.lower():
            astound_df = df.reset_index()
            break

    if astound_df is None:
        print("No Astound data found for before/after analysis.")
        return

    # Localize timestamps for comparison with CABLE_CUTOFF
    # The data may not have timezone info, so we need to localize it
    if astound_df["timestamp"].dt.tz is None:
        astound_df["timestamp"] = astound_df["timestamp"].dt.tz_localize("America/Los_Angeles")

    # Split at CABLE_CUTOFF
    before_mask = astound_df["timestamp"] < CABLE_CUTOFF
    after_mask = astound_df["timestamp"] >= CABLE_CUTOFF

    before_df = astound_df[before_mask].copy()
    after_df = astound_df[after_mask].copy()

    before_df["Period"] = "Before Cable"
    after_df["Period"] = "After Cable"

    combined_df = pd.concat([before_df, after_df], ignore_index=True)

    n_before = len(before_df)
    n_after = len(after_df)

    if n_before == 0 or n_after == 0:
        print(f"Insufficient data: Before={n_before}, After={n_after}")
        return

    # Create 2-panel figure (download, upload)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    # Color palette - distinct colors for before/after
    palette = {"Before Cable": "#e74c3c", "After Cable": "#27ae60"}

    # Download boxplot
    sns.boxplot(
        data=combined_df, x="Period", y="download_mbps", ax=axes[0],
        hue="Period", palette=palette, order=["Before Cable", "After Cable"],
        hue_order=["Before Cable", "After Cable"], legend=False,
        width=0.5, linewidth=1.5
    )
    axes[0].set_ylabel("Download Speed (Mbps)")
    axes[0].set_xlabel("")
    axes[0].set_title("Download Speed: Before vs After Cable Replacement")

    # Add sample counts and medians as annotations
    for i, period in enumerate(["Before Cable", "After Cable"]):
        period_data = combined_df[combined_df["Period"] == period]["download_mbps"]
        median = period_data.median()
        n = len(period_data)
        axes[0].text(i, axes[0].get_ylim()[1] * 0.95, f"n={n}\nmed={median:.0f}",
                     ha="center", va="top", fontsize=10, fontweight="bold")

    axes[0].grid(True, alpha=0.3, axis="y")

    # Upload boxplot
    sns.boxplot(
        data=combined_df, x="Period", y="upload_mbps", ax=axes[1],
        hue="Period", palette=palette, order=["Before Cable", "After Cable"],
        hue_order=["Before Cable", "After Cable"], legend=False,
        width=0.5, linewidth=1.5
    )
    axes[1].set_ylabel("Upload Speed (Mbps)")
    axes[1].set_xlabel("")
    axes[1].set_title("Upload Speed: Before vs After Cable Replacement")

    # Add sample counts and medians
    for i, period in enumerate(["Before Cable", "After Cable"]):
        period_data = combined_df[combined_df["Period"] == period]["upload_mbps"]
        median = period_data.median()
        n = len(period_data)
        axes[1].text(i, axes[1].get_ylim()[1] * 0.95, f"n={n}\nmed={median:.0f}",
                     ha="center", va="top", fontsize=10, fontweight="bold")

    axes[1].grid(True, alpha=0.3, axis="y")

    # Add figure title with date info
    fig.suptitle(
        f"Astound Internet Performance: Cable Replacement Impact\n"
        f"(Cutoff: March 19, 2026 at 2:00 PM PDT)",
        fontsize=12, fontweight="bold"
    )

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "astound_before_after_boxplot.png", dpi=150)
    plt.show()

    # Print summary statistics
    print("\n" + "=" * 60)
    print("ASTOUND BEFORE/AFTER CABLE REPLACEMENT SUMMARY")
    print("=" * 60)
    print(f"\nBefore Cable (n={n_before}):")
    print(f"  Download: {before_df['download_mbps'].median():.1f} Mbps median "
          f"({before_df['download_mbps'].min():.1f} - {before_df['download_mbps'].max():.1f})")
    print(f"  Upload: {before_df['upload_mbps'].median():.1f} Mbps median")
    print(f"\nAfter Cable (n={n_after}):")
    print(f"  Download: {after_df['download_mbps'].median():.1f} Mbps median "
          f"({after_df['download_mbps'].min():.1f} - {after_df['download_mbps'].max():.1f})")
    print(f"  Upload: {after_df['upload_mbps'].median():.1f} Mbps median")

    improvement = after_df['download_mbps'].median() / before_df['download_mbps'].median()
    print(f"\n  → Download improvement: {improvement:.1f}x faster")

    print(f"\nSaved plot to {PLOTS_DIR / 'astound_before_after_boxplot.png'}")


def plot_isp_comparison_boxplot(speed_data: dict[str, pd.DataFrame]):
    """Compare ISPs using only post-cable data for fair comparison.

    Filters all ISP data to after March 19, 2026 2pm PDT to ensure
    Astound data only includes the post-cable-replacement period.
    """
    if len(speed_data) < 2:
        print("Need at least 2 ISPs for comparison boxplot.")
        return

    # Collect post-cable data for each ISP
    comparison_data = []

    for isp, df in speed_data.items():
        df_copy = df.reset_index()

        # Localize timestamps if needed
        if df_copy["timestamp"].dt.tz is None:
            df_copy["timestamp"] = df_copy["timestamp"].dt.tz_localize("America/Los_Angeles")

        # Filter to post-cable period
        post_cable_df = df_copy[df_copy["timestamp"] >= CABLE_CUTOFF].copy()
        post_cable_df["ISP"] = isp.upper()
        comparison_data.append(post_cable_df)

    combined_df = pd.concat(comparison_data, ignore_index=True)

    # Get ISP names and counts
    isp_counts = combined_df.groupby("ISP").size()

    if len(isp_counts) == 0:
        print("No post-cable data available for comparison.")
        return

    # Create 3-panel figure (download, upload, ping)
    fig, axes = plt.subplots(1, 3, figsize=(15, 6))

    # Use distinct colors for ISPs
    palette = sns.color_palette("husl", n_colors=len(speed_data))

    # Download boxplot
    sns.boxplot(
        data=combined_df, x="ISP", y="download_mbps", ax=axes[0],
        hue="ISP", palette=palette, legend=False,
        width=0.5, linewidth=1.5
    )
    axes[0].set_ylabel("Download Speed (Mbps)")
    axes[0].set_xlabel("")
    axes[0].set_title("Download Speed Comparison")

    # Add sample counts and medians
    isp_order = sorted(combined_df["ISP"].unique())
    for i, isp in enumerate(isp_order):
        isp_data = combined_df[combined_df["ISP"] == isp]["download_mbps"]
        median = isp_data.median()
        n = len(isp_data)
        axes[0].text(i, axes[0].get_ylim()[1] * 0.95, f"n={n}\nmed={median:.0f}",
                     ha="center", va="top", fontsize=9, fontweight="bold")

    axes[0].grid(True, alpha=0.3, axis="y")

    # Upload boxplot
    sns.boxplot(
        data=combined_df, x="ISP", y="upload_mbps", ax=axes[1],
        hue="ISP", palette=palette, legend=False,
        width=0.5, linewidth=1.5
    )
    axes[1].set_ylabel("Upload Speed (Mbps)")
    axes[1].set_xlabel("")
    axes[1].set_title("Upload Speed Comparison")

    for i, isp in enumerate(isp_order):
        isp_data = combined_df[combined_df["ISP"] == isp]["upload_mbps"]
        median = isp_data.median()
        n = len(isp_data)
        axes[1].text(i, axes[1].get_ylim()[1] * 0.95, f"n={n}\nmed={median:.0f}",
                     ha="center", va="top", fontsize=9, fontweight="bold")

    axes[1].grid(True, alpha=0.3, axis="y")

    # Ping boxplot
    sns.boxplot(
        data=combined_df, x="ISP", y="ping_ms", ax=axes[2],
        hue="ISP", palette=palette, legend=False,
        width=0.5, linewidth=1.5
    )
    axes[2].set_ylabel("Ping Latency (ms)")
    axes[2].set_xlabel("")
    axes[2].set_title("Latency Comparison")

    for i, isp in enumerate(isp_order):
        isp_data = combined_df[combined_df["ISP"] == isp]["ping_ms"]
        median = isp_data.median()
        n = len(isp_data)
        axes[2].text(i, axes[2].get_ylim()[1] * 0.95, f"n={n}\nmed={median:.0f}",
                     ha="center", va="top", fontsize=9, fontweight="bold")

    axes[2].grid(True, alpha=0.3, axis="y")

    # Figure title
    fig.suptitle(
        f"ISP Performance Comparison (Post-Cable Data Only)\n"
        f"(Data from March 19, 2026 2:00 PM PDT onwards)",
        fontsize=12, fontweight="bold"
    )

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "astound_vs_tmobile_boxplot.png", dpi=150)
    plt.show()

    # Print summary statistics
    print("\n" + "=" * 60)
    print("ISP COMPARISON SUMMARY (Post-Cable Data Only)")
    print("=" * 60)

    for isp in isp_order:
        isp_df = combined_df[combined_df["ISP"] == isp]
        n = len(isp_df)
        print(f"\n{isp} (n={n}):")
        print(f"  Download: {isp_df['download_mbps'].median():.1f} Mbps median "
              f"({isp_df['download_mbps'].min():.1f} - {isp_df['download_mbps'].max():.1f})")
        print(f"  Upload: {isp_df['upload_mbps'].median():.1f} Mbps median "
              f"({isp_df['upload_mbps'].min():.1f} - {isp_df['upload_mbps'].max():.1f})")
        print(f"  Ping: {isp_df['ping_ms'].median():.1f} ms median")

    print(f"\nSaved plot to {PLOTS_DIR / 'astound_vs_tmobile_boxplot.png'}")


def main():
    # Ensure plots directory exists
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    speed_data = load_speed_data()
    conn_data = load_connectivity_data()

    if not speed_data and not conn_data:
        print("No data files found in data/ directory.")
        print("Run speedtest_monitor.py or connectivity_check.py first.")
        return

    summary(speed_data, conn_data)

    # Outlier analysis
    speed_outliers = analyze_outliers(speed_data) if speed_data else {}
    latency_outliers = analyze_latency_outliers(conn_data) if conn_data else {}

    if speed_outliers or latency_outliers:
        outlier_summary(speed_outliers, latency_outliers)
        plot_outlier_time_of_day(speed_outliers, latency_outliers)
        # Normalized rate analysis
        normalized_outlier_summary(speed_data, conn_data, speed_outliers, latency_outliers)
        plot_normalized_outlier_rates(speed_data, conn_data, speed_outliers, latency_outliers)

    if speed_data:
        plot_speed_comparison(speed_data)
        plot_time_of_day(speed_data)
        # Before/After cable replacement analysis for Astound
        plot_astound_before_after_boxplot(speed_data)
        # Fair ISP comparison using only post-cable data
        plot_isp_comparison_boxplot(speed_data)

    if conn_data:
        plot_connectivity_comparison(conn_data)


if __name__ == "__main__":
    main()
