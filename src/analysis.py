"""
Fleet Cycle-Time & Production Analysis
Komatsu Modular — Data Analyst Test Case

Reads the raw haul-cycle dataset, cleans/derives the metrics used in the
dashboard and report, and exports:
  - dashboard/dashboard_data.json   (feeds dashboard/index.html)
  - images/chart_*.png              (used in report/Fleet_Analysis_Report.docx)

Usage:
    python src/analysis.py
"""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RAW_FILE = ROOT / "data" / "haul_cycle_data.xlsx"
DASHBOARD_DATA = ROOT / "dashboard" / "dashboard_data.json"
IMAGES_DIR = ROOT / "images"

YELLOW = "#e0a500"
DARK = "#1c1b18"
STEEL = "#7d8790"
BAD = "#c0392b"


def load_data() -> pd.DataFrame:
    df = pd.read_excel(RAW_FILE, sheet_name="Data Actual Cycle")
    df = df.rename(
        columns={
            "ID Truck": "ExcavatorID",
            "Truck Type": "ExcavatorType",
            "ID Truck.1": "TruckID",
            "Truck Type.1": "TruckType",
        }
    )
    for c in [
        "EmptyTravelDuration",
        "QueueTime",
        "SpotTime",
        "LoadingTime",
        "FullTravelDuration",
        "DumpingTime",
    ]:
        df[c + "_min"] = df[c] / 60

    df["TotalCycleTime_min"] = (
        df[
            [
                "EmptyTravelDuration",
                "QueueTime",
                "SpotTime",
                "LoadingTime",
                "FullTravelDuration",
                "DumpingTime",
            ]
        ].sum(axis=1)
        / 60
    )
    df["ZeroTon"] = df["Tons"] == 0
    df["Hour"] = df["ArriveAtFront"].dt.hour
    return df


def build_dashboard_json(df: pd.DataFrame) -> dict:
    out = {}

    out["kpi"] = {
        "total_cycles": int(len(df)),
        "total_tons": int(df["Tons"].sum()),
        "avg_payload_all": round(df["Tons"].mean(), 1),
        "avg_payload_loaded": round(df.loc[~df["ZeroTon"], "Tons"].mean(), 1),
        "zero_ton_pct": round(df["ZeroTon"].mean() * 100, 1),
        "zero_ton_count": int(df["ZeroTon"].sum()),
        "avg_cycle_time": round(df["TotalCycleTime_min"].mean(), 1),
        "n_excavators": int(df["ExcavatorID"].nunique()),
        "n_trucks": int(df["TruckID"].nunique()),
        "shift_start": str(df["ArriveAtFront"].min()),
        "shift_end": str(df["ArriveAtFront"].max()),
    }

    out["cycletime"] = {
        "categories": ["Queue", "Spot", "Load", "Full Travel", "Empty Travel", "Dump"],
        "PC1250_actual": [
            round(df[df.ExcavatorType == "PC1250"][c].mean(), 2)
            for c in [
                "QueueTime_min",
                "SpotTime_min",
                "LoadingTime_min",
                "FullTravelDuration_min",
                "EmptyTravelDuration_min",
                "DumpingTime_min",
            ]
        ],
        "PC1250_plan": [2.5, 0.9, 3.3, None, None, 1.5],
        "PC2000_actual": [
            round(df[df.ExcavatorType == "PC2000"][c].mean(), 2)
            for c in [
                "QueueTime_min",
                "SpotTime_min",
                "LoadingTime_min",
                "FullTravelDuration_min",
                "EmptyTravelDuration_min",
                "DumpingTime_min",
            ]
        ],
        "PC2000_plan": [None, 0.9, 4.0, None, None, None],
    }

    pl = df.groupby("ExcavatorType")["Tons"].mean().round(1)
    plnz = df[~df["ZeroTon"]].groupby("ExcavatorType")["Tons"].mean().round(1)
    out["payload"] = {
        "types": ["PC1250", "PC2000"],
        "actual_all": [float(pl["PC1250"]), float(pl["PC2000"])],
        "actual_loaded": [float(plnz["PC1250"]), float(plnz["PC2000"])],
        "target": [95, 95],
    }

    h = (
        df.groupby("Hour")
        .agg(cycles=("Tons", "count"), tons=("Tons", "sum"), avg_queue=("QueueTime_min", "mean"))
        .round(2)
    )
    out["hourly"] = {
        "hours": [f"{int(x)}:00" for x in h.index],
        "cycles": h["cycles"].tolist(),
        "tons": h["tons"].tolist(),
        "avg_queue": h["avg_queue"].tolist(),
    }

    m = (
        df.groupby("MaterialType")
        .agg(cycles=("Tons", "count"), tons=("Tons", "sum"))
        .sort_values("tons", ascending=False)
        .round(1)
    )
    out["material"] = {"labels": m.index.tolist(), "tons": m["tons"].tolist(), "cycles": m["cycles"].tolist()}

    r = (
        df.groupby(["LoadLocation", "DumpLocation"])
        .agg(
            cycles=("Tons", "count"),
            avg_tons=("Tons", "mean"),
            avg_full_travel=("FullTravelDuration_min", "mean"),
            avg_empty_travel=("EmptyTravelDuration_min", "mean"),
        )
        .round(2)
        .sort_values("cycles", ascending=False)
    )
    out["routes"] = [
        {
            "route": f"{i[0]} \u2192 {i[1]}",
            "cycles": int(v["cycles"]),
            "avg_tons": float(v["avg_tons"]),
            "avg_full_travel": float(v["avg_full_travel"]),
            "avg_empty_travel": float(v["avg_empty_travel"]),
        }
        for i, v in r.iterrows()
    ]

    e = (
        df.groupby(["ExcavatorID", "ExcavatorType"])
        .size()
        .reset_index(name="cycles")
        .sort_values("cycles", ascending=False)
    )
    out["excavator_util"] = e.to_dict("records")

    z = df[df["ZeroTon"]].groupby(["ExcavatorType", "LoadLocation"]).size().reset_index(name="count")
    out["zero_ton_detail"] = z.to_dict("records")

    et = (
        df.groupby("ExcavatorType")
        .agg(cycles=("Tons", "count"), total_tons=("Tons", "sum"), avg_cycle=("TotalCycleTime_min", "mean"))
        .round(2)
    )
    out["excavator_type_summary"] = et.reset_index().to_dict("records")

    return out


def make_charts(df: pd.DataFrame, D: dict) -> None:
    IMAGES_DIR.mkdir(exist_ok=True)
    plt.rcParams["font.size"] = 10

    # Cycle time actual vs plan
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    for ax, typ in zip(axes, ["PC1250", "PC2000"]):
        cats = D["cycletime"]["categories"]
        actual = D["cycletime"][f"{typ}_actual"]
        plan = D["cycletime"][f"{typ}_plan"]
        x = np.arange(len(cats))
        ax.bar(x, actual, color=YELLOW, label="Actual", width=0.6)
        plan_x = [xi for xi, p in zip(x, plan) if p is not None]
        plan_y = [p for p in plan if p is not None]
        ax.plot(plan_x, plan_y, "o--", color=DARK, label="Plan")
        ax.set_xticks(x)
        ax.set_xticklabels(cats, rotation=40, ha="right", fontsize=8)
        ax.set_title(typ, fontweight="bold")
        ax.set_ylabel("minutes")
        ax.legend(fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(IMAGES_DIR / "chart_cycletime.png", dpi=160)
    plt.close()

    # Payload vs target
    fig, ax = plt.subplots(figsize=(6, 3.2))
    types = D["payload"]["types"]
    x = np.arange(len(types))
    w = 0.28
    ax.bar(x - w, D["payload"]["actual_all"], width=w, label="Actual (all cycles)", color=STEEL)
    ax.bar(x, D["payload"]["actual_loaded"], width=w, label="Actual (loaded only)", color=YELLOW)
    ax.bar(x + w, D["payload"]["target"], width=w, label="Target", color=DARK)
    ax.set_xticks(x)
    ax.set_xticklabels(types)
    ax.set_ylabel("tons")
    ax.set_title("Payload vs 95t Target", fontweight="bold")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(IMAGES_DIR / "chart_payload.png", dpi=160)
    plt.close()

    # Hourly production + queue
    fig, ax1 = plt.subplots(figsize=(7, 3.3))
    hours = D["hourly"]["hours"]
    ax1.bar(hours, D["hourly"]["tons"], color=YELLOW, label="Tons hauled")
    ax1.set_ylabel("tons")
    ax2 = ax1.twinx()
    ax2.plot(hours, D["hourly"]["avg_queue"], "o-", color=BAD, label="Avg queue (min)")
    ax2.set_ylabel("queue time (min)")
    ax1.set_title("Hourly Production & Queue Time", fontweight="bold")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")
    ax1.spines[["top"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(IMAGES_DIR / "chart_hourly.png", dpi=160)
    plt.close()

    # Excavator utilization
    fig, ax = plt.subplots(figsize=(8, 3.6))
    excs = D["excavator_util"]
    colors = [YELLOW if e["ExcavatorType"] == "PC1250" else STEEL for e in excs]
    ax.bar([e["ExcavatorID"] for e in excs], [e["cycles"] for e in excs], color=colors)
    ax.set_ylabel("cycles")
    ax.set_title("Cycles Served per Excavator Unit", fontweight="bold")
    plt.xticks(rotation=90, fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(IMAGES_DIR / "chart_excutil.png", dpi=160)
    plt.close()


def main():
    df = load_data()
    D = build_dashboard_json(df)
    DASHBOARD_DATA.parent.mkdir(exist_ok=True)
    DASHBOARD_DATA.write_text(json.dumps(D, indent=2))
    make_charts(df, D)
    print(f"Wrote {DASHBOARD_DATA}")
    print(f"Wrote chart images to {IMAGES_DIR}")


if __name__ == "__main__":
    main()
