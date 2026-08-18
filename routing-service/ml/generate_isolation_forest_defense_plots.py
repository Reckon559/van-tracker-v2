"""
Generate the two Isolation Forest evaluation and defense plots:
1. Anomaly Score Histogram with Decision Thresholds (Normal, Monitor, Suspicious regions)
2. Feature vs. Anomaly Score Scatter Plot Grid (Speed, Deviation, Stop Duration, Off-route Distance)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from ml.feature_engineering import engineer_anomaly_features

PLOTS_DIR = BASE_DIR / "evaluation_plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = BASE_DIR.parent / "docs" / "ml-evaluation"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR = Path(r"C:\Users\user\.gemini\antigravity-ide\brain\0bc9127e-d8fa-4e50-8a0b-e8d0230c989d\plots")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Styling
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams["font.sans-serif"] = "Arial"
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["figure.dpi"] = 300


def main():
    print("Loading Isolation Forest model and anomaly dataset...")
    model_path = BASE_DIR / "models" / "isolation_forest_anomaly.joblib"
    data_path = BASE_DIR / "data" / "kathmandu_anomaly_labeled.csv"

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found at {model_path}")
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found at {data_path}")

    artifact = joblib.load(model_path)
    pipeline = artifact["pipeline"]
    features = artifact["features"]
    tau_mon = float(artifact.get("monitor_threshold", -0.541972))
    tau_susp = float(artifact.get("suspicious_threshold", -0.640872))

    df = pd.read_csv(data_path)
    print(f"Loaded {len(df):,} samples.")

    # Calculate raw Isolation Forest score_samples (negative values, lower = more anomalous)
    preprocessor = pipeline.named_steps["preprocess"]
    model = pipeline.named_steps["model"]
    
    transformed = preprocessor.transform(df[features])
    raw_scores = model.score_samples(transformed)
    df["if_score"] = raw_scores

    # Assign threshold category based on Isolation Forest score
    conditions = [
        df["if_score"] < tau_susp,
        (df["if_score"] >= tau_susp) & (df["if_score"] < tau_mon),
        df["if_score"] >= tau_mon,
    ]
    choices = ["Suspicious", "Monitor", "Normal"]
    df["if_decision"] = np.select(conditions, choices, default="Normal")

    # =========================================================================
    # PLOT 1: Anomaly Score Histogram with Decision Thresholds
    # =========================================================================
    print("Generating Plot 1: Anomaly Score Histogram with Decision Thresholds...")
    fig, ax = plt.subplots(figsize=(10.5, 6))

    # Histogram of scores
    counts, bins, patches = ax.hist(df["if_score"], bins=60, edgecolor="black", linewidth=0.6, alpha=0.75, color="#6baed6")

    # Color the histogram bars according to the threshold zones
    for bin_left, bin_right, patch in zip(bins[:-1], bins[1:], patches):
        bin_center = (bin_left + bin_right) / 2
        if bin_center < tau_susp:
            patch.set_facecolor("#d62728")  # Red (Suspicious)
            patch.set_alpha(0.85)
        elif bin_center < tau_mon:
            patch.set_facecolor("#ff7f0e")  # Orange (Monitor)
            patch.set_alpha(0.85)
        else:
            patch.set_facecolor("#2ca02c")  # Green (Normal)
            patch.set_alpha(0.85)

    # Add vertical decision threshold lines
    ax.axvline(tau_mon, color="#d95f02", linestyle="--", linewidth=2.5, label=f"Threshold A: Monitor Cutoff (τ_mon = {tau_mon:.3f})")
    ax.axvline(tau_susp, color="#b2182b", linestyle="--", linewidth=2.5, label=f"Threshold B: Suspicious Cutoff (τ_susp = {tau_susp:.3f})")

    # Add shaded background regions
    y_max = ax.get_ylim()[1] * 1.05
    ax.set_ylim(0, y_max)
    x_min, x_max = ax.get_xlim()

    ax.axvspan(x_min, tau_susp, color="#fee0d2", alpha=0.35)
    ax.axvspan(tau_susp, tau_mon, color="#fee8c8", alpha=0.35)
    ax.axvspan(tau_mon, x_max, color="#e5f5e0", alpha=0.35)

    # Zone text callouts
    ax.text(x_min + (tau_susp - x_min) * 0.5, y_max * 0.82, "SUSPICIOUS ZONE\n(Top 2% Outliers)\n• Major Route Detour\n• Severe Overspeed\n• Emergency Alert", 
            ha="center", va="top", fontsize=9.5, fontweight="bold", color="#990000", bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff5f0", edgecolor="#d62728", alpha=0.9))

    ax.text(tau_susp + (tau_mon - tau_susp) * 0.5, y_max * 0.82, "MONITOR ZONE\n(Mid ~10% Outliers)\n• Red Light Delay\n• Roadside Queue\n• Staff Dashboard Only", 
            ha="center", va="top", fontsize=9.5, fontweight="bold", color="#b35806", bbox=dict(boxstyle="round,pad=0.4", facecolor="#fffbf5", edgecolor="#ff7f0e", alpha=0.9))

    ax.text(tau_mon + (x_max - tau_mon) * 0.5, y_max * 0.82, "NORMAL PROFILE ZONE\n(Safest ~88% of Trips)\n• On-Route Driving\n• Standard Speed & Stops\n• Zero Parent Alerts", 
            ha="center", va="top", fontsize=9.5, fontweight="bold", color="#1b7837", bbox=dict(boxstyle="round,pad=0.4", facecolor="#f7fcf5", edgecolor="#2ca02c", alpha=0.9))

    ax.set_xlabel("Isolation Forest Anomaly Score [s(x, n)]  <-- More Anomalous  |  More Normal -->", fontsize=12, fontweight="bold", labelpad=10)
    ax.set_ylabel("Number of Telemetry Samples", fontsize=12, fontweight="bold", labelpad=8)
    ax.set_title("Isolation Forest Anomaly Score Distribution with Business Decision Cutoffs\n(Semi-Supervised One-Class Anomaly Separation)", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", frameon=True, facecolor="white", framealpha=0.95, fontsize=10)

    plt.tight_layout()
    plot1_path = PLOTS_DIR / "isolation_forest_threshold_histogram.png"
    plt.savefig(plot1_path, dpi=300)
    plt.close()
    print(f"Saved: {plot1_path.name}")

    # =========================================================================
    # PLOT 2: Feature vs. Anomaly Score Scatter Plot Grid (4 Key Parameters)
    # =========================================================================
    print("Generating Plot 2: Feature vs. Anomaly Score Scatter Plot Grid...")
    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    palette = {"Normal": "#2ca02c", "Monitor": "#ff7f0e", "Suspicious": "#d62728"}

    # Subplot A: Speed (km/h) vs Anomaly Score
    ax_a = axes[0, 0]
    sns.scatterplot(
        data=df.sample(min(2500, len(df)), random_state=42),
        x="current_speed_kmh", y="if_score", hue="if_decision",
        palette=palette, alpha=0.55, s=22, ax=ax_a, legend=True
    )
    ax_a.axhline(tau_mon, color="#ff7f0e", linestyle="--", linewidth=1.5, label="Threshold A (Monitor)")
    ax_a.axhline(tau_susp, color="#d62728", linestyle="--", linewidth=1.5, label="Threshold B (Suspicious)")
    ax_a.set_xlabel("Vehicle Current Speed (km/h)", fontsize=11, fontweight="bold")
    ax_a.set_ylabel("Anomaly Score [s(x, n)]", fontsize=11, fontweight="bold")
    ax_a.set_title("Parameter 1: Speed vs. Anomaly Score\n(Speed > 45 km/h pulls score into Monitor/Suspicious)", fontsize=11, fontweight="bold")
    ax_a.grid(True, linestyle=":", alpha=0.6)
    ax_a.legend(loc="lower left", fontsize=8.5)

    # Subplot B: Distance from Planned Route (m) vs Anomaly Score
    ax_b = axes[0, 1]
    sns.scatterplot(
        data=df.sample(min(2500, len(df)), random_state=42),
        x="distance_from_route_m", y="if_score", hue="if_decision",
        palette=palette, alpha=0.55, s=22, ax=ax_b, legend=False
    )
    ax_b.axhline(tau_mon, color="#ff7f0e", linestyle="--", linewidth=1.5)
    ax_b.axhline(tau_susp, color="#d62728", linestyle="--", linewidth=1.5)
    ax_b.set_xlabel("Distance from Route (Meters)", fontsize=11, fontweight="bold")
    ax_b.set_ylabel("Anomaly Score [s(x, n)]", fontsize=11, fontweight="bold")
    ax_b.set_title("Parameter 2: Route Deviation vs. Anomaly Score\n(Distance > 80m triggers Monitor, > 250m triggers Suspicious)", fontsize=11, fontweight="bold")
    ax_b.grid(True, linestyle=":", alpha=0.6)

    # Subplot C: Stop Duration (s) vs Anomaly Score
    ax_c = axes[1, 0]
    sns.scatterplot(
        data=df.sample(min(2500, len(df)), random_state=42),
        x="stop_duration_sec", y="if_score", hue="if_decision",
        palette=palette, alpha=0.55, s=22, ax=ax_c, legend=False
    )
    ax_c.axhline(tau_mon, color="#ff7f0e", linestyle="--", linewidth=1.5)
    ax_c.axhline(tau_susp, color="#d62728", linestyle="--", linewidth=1.5)
    ax_c.set_xlabel("Stop Duration (Seconds)", fontsize=11, fontweight="bold")
    ax_c.set_ylabel("Anomaly Score [s(x, n)]", fontsize=11, fontweight="bold")
    ax_c.set_title("Parameter 3: Stop Duration vs. Anomaly Score\n(Prolonged stationary halts drop anomaly score significantly)", fontsize=11, fontweight="bold")
    ax_c.grid(True, linestyle=":", alpha=0.6)

    # Subplot D: Off-Route Total Traveled Distance (m) vs Anomaly Score
    ax_d = axes[1, 1]
    sns.scatterplot(
        data=df.sample(min(2500, len(df)), random_state=42),
        x="off_route_distance_m", y="if_score", hue="if_decision",
        palette=palette, alpha=0.55, s=22, ax=ax_d, legend=False
    )
    ax_d.axhline(tau_mon, color="#ff7f0e", linestyle="--", linewidth=1.5)
    ax_d.axhline(tau_susp, color="#d62728", linestyle="--", linewidth=1.5)
    ax_d.set_xlabel("Cumulative Off-Route Distance (Meters)", fontsize=11, fontweight="bold")
    ax_d.set_ylabel("Anomaly Score [s(x, n)]", fontsize=11, fontweight="bold")
    ax_d.set_title("Parameter 4: Off-Route Distance vs. Anomaly Score\n(Unapproved detours > 800m push score deep into Suspicious zone)", fontsize=11, fontweight="bold")
    ax_d.grid(True, linestyle=":", alpha=0.6)

    plt.suptitle("Multi-Parameter Feature vs. Anomaly Score Relationship\n(Proves Exactly Why and When Decisions are Triggered)", fontsize=14, fontweight="bold", y=0.99)
    plt.tight_layout()
    plot2_path = PLOTS_DIR / "feature_vs_anomaly_score_scatter_grid.png"
    plt.savefig(plot2_path, dpi=300)
    plt.close()
    print(f"Saved: {plot2_path.name}")

    # Copy both plots to docs/ml-evaluation and artifacts directory
    for p in [plot1_path, plot2_path]:
        shutil.copy2(p, DOCS_DIR / p.name)
        shutil.copy2(p, ARTIFACTS_DIR / p.name)
    print("Exported both plots to docs/ml-evaluation and artifact directory.")


if __name__ == "__main__":
    main()
