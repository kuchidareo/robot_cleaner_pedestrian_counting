from __future__ import annotations

import argparse
import csv
import io
import os
import statistics
import tempfile
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from transform_thermalarray import frame_to_rgb, iter_frames


matplotlib.use("Agg")
import matplotlib.pyplot as plt


THERMAL_PIXEL_SIZE = 20
PANEL_WIDTH = 640
PANEL_HEIGHT = 480
CANVAS_WIDTH = PANEL_WIDTH * 2
CANVAS_HEIGHT = 1280
INFO_HEIGHT = 170
PLOTS_HEIGHT = CANVAS_HEIGHT - PANEL_HEIGHT - INFO_HEIGHT
DEFAULT_RUN_DIR = Path("out/20260330_1434")
DEFAULT_OUTPUT_DIR = DEFAULT_RUN_DIR / "aligned_aggregate_jpegs"
HISTORY_POINTS = 50
PLOT_DPI = 140
PLOT_BG = "#ffffff"


@dataclass(frozen=True)
class TimedRow:
    timestamp: float
    row: dict[str, Any]


@dataclass(frozen=True)
class SensorSeries:
    rows: list[TimedRow]
    timestamps: list[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render aligned aggregate JPEGs with matplotlib trend plots."
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--annotation-tolerance", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def make_series(rows: list[TimedRow]) -> SensorSeries:
    return SensorSeries(rows=rows, timestamps=[row.timestamp for row in rows])


def load_csv_rows(csv_path: Path) -> SensorSeries:
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [TimedRow(timestamp=float(row["timestamp"]), row=row) for row in reader]
    return make_series(rows)


def load_thermal_rows(csv_path: Path) -> SensorSeries:
    rows: list[TimedRow] = []
    for _, timestamp, frame in iter_frames(csv_path):
        rows.append(TimedRow(timestamp=float(timestamp), row={"frame": frame}))
    return make_series(rows)


def estimate_fps(series: SensorSeries) -> float:
    if len(series.rows) < 2:
        return 0.0
    duration = series.rows[-1].timestamp - series.rows[0].timestamp
    return (len(series.rows) - 1) / duration if duration > 0 else 0.0


def median_interval(series: SensorSeries) -> float:
    if len(series.rows) < 2:
        return 0.0
    deltas = [series.rows[i + 1].timestamp - series.rows[i].timestamp for i in range(len(series.rows) - 1)]
    return statistics.median(deltas)


def nearest_row(series: SensorSeries, target_ts: float) -> tuple[TimedRow, float]:
    pos = bisect_left(series.timestamps, target_ts)
    candidates: list[TimedRow] = []
    if pos < len(series.rows):
        candidates.append(series.rows[pos])
    if pos > 0:
        candidates.append(series.rows[pos - 1])
    best = min(candidates, key=lambda row: abs(row.timestamp - target_ts))
    return best, abs(best.timestamp - target_ts)


def latest_history(series: SensorSeries, target_ts: float, count: int = HISTORY_POINTS) -> list[TimedRow]:
    if not series.rows:
        return []
    pos = bisect_left(series.timestamps, target_ts)
    end = pos + 1 if pos < len(series.rows) and series.timestamps[pos] <= target_ts else pos
    if end <= 0:
        end = 1
    start = max(0, end - count)
    return series.rows[start:end]


def annotation_value(annotation_series: SensorSeries, target_ts: float, tolerance: float) -> tuple[bool, float | None]:
    if not annotation_series.rows:
        return False, None
    row, delta = nearest_row(annotation_series, target_ts)
    if delta <= tolerance:
        return row.row["annotation"].strip().lower() == "true", delta
    return False, None


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("Menlo.ttc", "Menlo.ttc", "Arial Unicode.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def fmt_time(ts: float) -> str:
    whole = int(ts)
    frac = int(round((ts - whole) * 10))
    hours = (whole // 3600) % 24
    minutes = (whole // 60) % 60
    seconds = whole % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{frac}"


def history_values(history: list[TimedRow], key: str) -> tuple[list[float], list[str]]:
    return [float(row.row[key]) for row in history], [fmt_time(row.timestamp) for row in history]


def make_plot_image(
    *,
    title: str,
    values: list[float],
    labels: list[str],
    width: int,
    height: int,
    color: str,
) -> Image.Image:
    fig_w = width / PLOT_DPI
    fig_h = height / PLOT_DPI
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=PLOT_DPI)
    fig.patch.set_facecolor(PLOT_BG)
    ax.set_facecolor(PLOT_BG)

    if values:
        x = np.arange(len(values))
        ax.plot(x, values, color=color, linewidth=2.4, marker="o", markersize=3.2)
        ax.scatter([x[-1]], [values[-1]], color=color, s=44, zorder=3)
        tick_count = min(6, len(values))
        tick_positions = np.linspace(0, len(values) - 1, tick_count, dtype=int)
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([labels[i] for i in tick_positions], rotation=0, fontsize=8)
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])

    ax.set_title(title, fontsize=14, loc="left", pad=10)
    ax.grid(True, color="#e8e8e8", linewidth=0.8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(axis="y", labelsize=9)
    plt.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB").resize((width, height), Image.Resampling.LANCZOS)


def build_info_panel(lines: list[str]) -> Image.Image:
    image = Image.new("RGB", (CANVAS_WIDTH, INFO_HEIGHT), "#f7f7f7")
    draw = ImageDraw.Draw(image)
    body_font = load_font(20)
    draw.line((20, INFO_HEIGHT - 1, CANVAS_WIDTH - 20, INFO_HEIGHT - 1), fill="#d8d8d8", width=1)
    y = 10
    for line in lines:
        draw.text((20, y), line, fill="#111111", font=body_font)
        y += 26
    return image


def build_plots_panel(
    *,
    distance_values: list[float],
    distance_labels: list[str],
    motion_values: list[float],
    motion_labels: list[str],
    presence_values: list[float],
    presence_labels: list[str],
    ambient_values: list[float],
    ambient_labels: list[str],
) -> Image.Image:
    panel = Image.new("RGB", (CANVAS_WIDTH, PLOTS_HEIGHT), "#f7f7f7")
    margin = 20
    gap = 20
    height = (PLOTS_HEIGHT - gap - margin * 2) // 2
    col_w = (CANVAS_WIDTH - margin * 2 - gap * 2) // 3

    distance_plot = make_plot_image(
        title="Distance History",
        values=distance_values,
        labels=distance_labels,
        width=col_w,
        height=height,
        color="#2563eb",
    )
    motion_plot = make_plot_image(
        title="PIR Motion History",
        values=motion_values,
        labels=motion_labels,
        width=col_w,
        height=height,
        color="#dc2626",
    )
    presence_plot = make_plot_image(
        title="Presence History",
        values=presence_values,
        labels=presence_labels,
        width=col_w,
        height=height,
        color="#16a34a",
    )
    ambient_plot = make_plot_image(
        title="Ambient History",
        values=ambient_values,
        labels=ambient_labels,
        width=col_w,
        height=height,
        color="#d97706",
    )

    panel.paste(distance_plot, (margin, 10))
    panel.paste(motion_plot, (margin, height + gap))
    panel.paste(presence_plot, (margin + col_w + gap, height + gap))
    panel.paste(ambient_plot, (margin + (col_w + gap) * 2, height + gap))
    return panel


def build_top_panel(timercam_path: Path, thermal_rgb: np.ndarray) -> Image.Image:
    left = Image.open(timercam_path).convert("RGB").resize((PANEL_WIDTH, PANEL_HEIGHT), Image.Resampling.LANCZOS)
    right = Image.fromarray(thermal_rgb, mode="RGB").resize(
        (PANEL_WIDTH, PANEL_HEIGHT), Image.Resampling.NEAREST
    )
    top = Image.new("RGB", (CANVAS_WIDTH, PANEL_HEIGHT), "white")
    top.paste(left, (0, 0))
    top.paste(right, (PANEL_WIDTH, 0))
    return top


def format_info_lines(
    *,
    base_name: str,
    base_ts: float,
    thermal_row: TimedRow,
    distance_row: TimedRow,
    pir_row: TimedRow,
    annotation_flag: bool,
    annotation_delta: float | None,
    deltas: dict[str, float],
) -> list[str]:
    annotation_text = "True" if annotation_flag else "False"
    annotation_delta_text = "n/a" if annotation_delta is None else f"{annotation_delta:.3f}s"
    return [
        f"Base sensor: {base_name}   timestamp: {base_ts:.6f}",
        f"Thermal ts: {thermal_row.timestamp:.6f}   dt: {deltas['thermal']:.3f}s",
        f"Distance: {distance_row.row['distance_cm']} cm   ts: {distance_row.timestamp:.6f}   dt: {deltas['distance']:.3f}s",
        f"PIR ts: {pir_row.timestamp:.6f}   dt: {deltas['pir']:.3f}s   motion: {pir_row.row['motion']}   presence: {pir_row.row['presence']}   ambient: {pir_row.row['ambient']}",
        f"Annotation: {annotation_text}   match_dt: {annotation_delta_text}",
    ]


def compose_frame(
    *,
    timercam_path: Path,
    thermal_rgb: np.ndarray,
    info_lines: list[str],
    distance_values: list[float],
    distance_labels: list[str],
    motion_values: list[float],
    motion_labels: list[str],
    presence_values: list[float],
    presence_labels: list[str],
    ambient_values: list[float],
    ambient_labels: list[str],
) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#f7f7f7")
    canvas.paste(build_top_panel(timercam_path, thermal_rgb), (0, 0))
    canvas.paste(build_info_panel(info_lines), (0, PANEL_HEIGHT))
    canvas.paste(
        build_plots_panel(
            distance_values=distance_values,
            distance_labels=distance_labels,
            motion_values=motion_values,
            motion_labels=motion_labels,
            presence_values=presence_values,
            presence_labels=presence_labels,
            ambient_values=ambient_values,
            ambient_labels=ambient_labels,
        ),
        (0, PANEL_HEIGHT + INFO_HEIGHT),
    )
    return canvas


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    sensor_series = {
        "timercam1": load_csv_rows(run_dir / "timercam1.csv"),
        "main": load_thermal_rows(run_dir / "main.csv"),
        "distance": load_csv_rows(run_dir / "distance.csv"),
        "main_pir": load_csv_rows(run_dir / "main_pir.csv"),
    }
    annotation_series = load_csv_rows(run_dir / "annotation.csv")

    fps_by_sensor = {name: estimate_fps(series) for name, series in sensor_series.items()}
    base_name = min(fps_by_sensor, key=fps_by_sensor.get)
    base_series = sensor_series[base_name]
    annotation_tolerance = (
        args.annotation_tolerance
        if args.annotation_tolerance is not None
        else max(0.25, median_interval(base_series) / 2.0)
    )

    print("Sensor FPS:")
    for name, fps in fps_by_sensor.items():
        print(f"  {name}: {fps:.3f}")
    print(f"Base sensor: {base_name}")
    print(f"Annotation tolerance: {annotation_tolerance:.3f}s")

    thermal_series = sensor_series["main"]
    distance_series = sensor_series["distance"]
    pir_series = sensor_series["main_pir"]
    frame_total = len(base_series.rows) if args.limit is None else min(len(base_series.rows), args.limit)

    for index, base_row in enumerate(base_series.rows[:frame_total], start=1):
        base_ts = base_row.timestamp
        thermal_row, thermal_delta = nearest_row(thermal_series, base_ts)
        distance_row, distance_delta = nearest_row(distance_series, base_ts)
        pir_row, pir_delta = nearest_row(pir_series, base_ts)
        annotation_flag, annotation_delta = annotation_value(annotation_series, base_ts, annotation_tolerance)

        distance_history = latest_history(distance_series, distance_row.timestamp)
        pir_history = latest_history(pir_series, pir_row.timestamp)
        distance_values, distance_labels = history_values(distance_history, "distance_cm")
        motion_values, motion_labels = history_values(pir_history, "motion")
        presence_values, presence_labels = history_values(pir_history, "presence")
        ambient_values, ambient_labels = history_values(pir_history, "ambient")

        image = compose_frame(
            timercam_path=run_dir / "timercam1" / base_row.row["filename"],
            thermal_rgb=frame_to_rgb(thermal_row.row["frame"], THERMAL_PIXEL_SIZE),
            info_lines=format_info_lines(
                base_name=base_name,
                base_ts=base_ts,
                thermal_row=thermal_row,
                distance_row=distance_row,
                pir_row=pir_row,
                annotation_flag=annotation_flag,
                annotation_delta=annotation_delta,
                deltas={"thermal": thermal_delta, "distance": distance_delta, "pir": pir_delta},
            ),
            distance_values=distance_values,
            distance_labels=distance_labels,
            motion_values=motion_values,
            motion_labels=motion_labels,
            presence_values=presence_values,
            presence_labels=presence_labels,
            ambient_values=ambient_values,
            ambient_labels=ambient_labels,
        )
        image.save(output_dir / f"aggregate_{index:04d}_{base_ts:.6f}.jpg", format="JPEG", quality=95)

    print(f"saved {frame_total} aggregate JPEG files to {output_dir}")


if __name__ == "__main__":
    main()
