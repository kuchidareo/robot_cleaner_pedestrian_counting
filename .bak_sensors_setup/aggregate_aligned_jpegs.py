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

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))

import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from transform_thermalarray import frame_to_rgb, iter_frames


matplotlib.use("Agg")
import matplotlib.pyplot as plt


THERMAL_PIXEL_SIZE = 20
CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 1280
GRID_ROWS = 2
GRID_COLS = 4
PANEL_WIDTH = CANVAS_WIDTH // GRID_COLS
PANEL_HEIGHT = 240
GRID_HEIGHT = PANEL_HEIGHT * GRID_ROWS
INFO_HEIGHT = 170
PLOTS_HEIGHT = CANVAS_HEIGHT - GRID_HEIGHT - INFO_HEIGHT
DEFAULT_RUN_DIR = Path("out/20260330_1434")
DEFAULT_OUTPUT_DIR_NAME = "aligned_aggregate_jpegs"
DEFAULT_MAX_MATCH_DELTA = 1.0
HISTORY_POINTS = 50
PLOT_DPI = 140
PLOT_BG = "#ffffff"

TIMER_CAMERAS = (
    ("timercam1", "TimerCam 1"),
    ("timercam2", "TimerCam 2"),
    ("timercam3", "TimerCam 3"),
    ("timercam4", "TimerCam 4"),
)
THERMAL_CAMERAS = (
    ("main", "Thermal 1", ("main.csv", "thermal_main.csv")),
    ("thermal2", "Thermal 2", ("thermal2.csv", "thermal_cam2.csv")),
    ("thermal3", "Thermal 3", ("thermal3.csv", "thermal_cam3.csv")),
    ("thermal4", "Thermal 4", ("thermal4.csv", "thermal_cam4.csv")),
)


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
        description="Render aligned aggregate JPEGs with tolerant missing sensor handling."
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <run-dir>/aligned_aggregate_jpegs.",
    )
    parser.add_argument("--annotation-tolerance", type=float, default=None)
    parser.add_argument(
        "--max-match-delta",
        type=float,
        default=DEFAULT_MAX_MATCH_DELTA,
        help=(
            "Maximum seconds allowed for nearest-frame visual matching. "
            f"Default: {DEFAULT_MAX_MATCH_DELTA:.1f}s."
        ),
    )
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def make_series(rows: list[TimedRow]) -> SensorSeries:
    rows = sorted(rows, key=lambda row: row.timestamp)
    return SensorSeries(rows=rows, timestamps=[row.timestamp for row in rows])


def empty_series() -> SensorSeries:
    return SensorSeries(rows=[], timestamps=[])


def load_csv_rows(csv_path: Path) -> SensorSeries:
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return empty_series()
        if "timestamp" not in reader.fieldnames:
            raise ValueError(f"{csv_path} is missing a timestamp column")

        rows: list[TimedRow] = []
        for row_index, row in enumerate(reader, start=2):
            timestamp_text = row.get("timestamp", "")
            if timestamp_text == "":
                continue
            try:
                timestamp = float(timestamp_text)
            except ValueError as exc:
                raise ValueError(f"{csv_path}:{row_index} has invalid timestamp {timestamp_text!r}") from exc
            rows.append(TimedRow(timestamp=timestamp, row=row))

    return make_series(rows)


def load_optional_csv_rows(csv_path: Path, label: str) -> SensorSeries:
    if not csv_path.exists():
        print(f"warning: {label} missing: {csv_path}")
        return empty_series()
    try:
        return load_csv_rows(csv_path)
    except (OSError, ValueError) as exc:
        print(f"warning: {label} could not be loaded from {csv_path}: {exc}")
        return empty_series()


def load_thermal_rows(csv_path: Path) -> SensorSeries:
    rows: list[TimedRow] = []
    for _, timestamp, frame in iter_frames(csv_path):
        rows.append(TimedRow(timestamp=float(timestamp), row={"frame": frame}))
    return make_series(rows)


def load_optional_thermal_rows(csv_path: Path, label: str) -> SensorSeries:
    if not csv_path.exists():
        print(f"warning: {label} missing: {csv_path}")
        return empty_series()
    try:
        return load_thermal_rows(csv_path)
    except (OSError, ValueError) as exc:
        print(f"warning: {label} could not be loaded from {csv_path}: {exc}")
        return empty_series()


def first_existing(run_dir: Path, candidates: tuple[str, ...]) -> Path:
    for candidate in candidates:
        path = run_dir / candidate
        if path.exists():
            return path
    return run_dir / candidates[0]


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
    if not series.rows:
        raise ValueError("cannot match nearest row from an empty series")

    pos = bisect_left(series.timestamps, target_ts)
    candidates: list[TimedRow] = []
    if pos < len(series.rows):
        candidates.append(series.rows[pos])
    if pos > 0:
        candidates.append(series.rows[pos - 1])
    best = min(candidates, key=lambda row: abs(row.timestamp - target_ts))
    return best, abs(best.timestamp - target_ts)


def optional_nearest_row(series: SensorSeries, target_ts: float) -> tuple[TimedRow | None, float | None]:
    if not series.rows:
        return None, None
    row, delta = nearest_row(series, target_ts)
    return row, delta


def auto_match_tolerance(series: SensorSeries, override: float | None) -> float:
    if override is not None:
        return override
    interval = median_interval(series)
    if interval > 0:
        return max(0.25, interval * 1.5)
    return 1.0


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
        return str(row.row.get("annotation", "")).strip().lower() == "true", delta
    return False, None


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("Menlo.ttc", "Arial Unicode.ttf", "Helvetica.ttc"):
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
    values: list[float] = []
    labels: list[str] = []
    for row in history:
        value = row.row.get(key)
        if value in (None, ""):
            continue
        try:
            values.append(float(value))
        except ValueError:
            continue
        labels.append(fmt_time(row.timestamp))
    return values, labels


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


def placeholder_panel(title: str, reason: str) -> Image.Image:
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), "#000000")
    draw = ImageDraw.Draw(image)
    title_font = load_font(22)
    body_font = load_font(16)
    draw.text((14, 12), title, fill="#ffffff", font=title_font)
    draw.text((14, 44), reason, fill="#bbbbbb", font=body_font)
    return image


def add_panel_label(image: Image.Image, title: str, detail: str | None = None) -> Image.Image:
    image = image.convert("RGB").resize((PANEL_WIDTH, PANEL_HEIGHT), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    title_font = load_font(18)
    detail_font = load_font(14)
    label_height = 48 if detail else 28
    draw.rectangle((0, 0, PANEL_WIDTH, label_height), fill=(0, 0, 0))
    draw.text((10, 5), title, fill="#ffffff", font=title_font)
    if detail:
        draw.text((10, 28), detail, fill="#dddddd", font=detail_font)
    return image


def resolve_image_path(run_dir: Path, camera_name: str, row: TimedRow) -> Path | None:
    for key in ("filename", "file", "filepath", "path", "image", "image_path"):
        value = row.row.get(key)
        if value:
            candidate = Path(value)
            if candidate.is_absolute():
                return candidate
            if len(candidate.parts) > 1:
                return run_dir / candidate
            return run_dir / camera_name / candidate
    return None


def build_timercam_panel(
    run_dir: Path,
    camera_name: str,
    label: str,
    series: SensorSeries,
    base_ts: float,
    tolerance: float,
) -> Image.Image:
    row, delta = optional_nearest_row(series, base_ts)
    if row is None:
        return placeholder_panel(label, "missing CSV/data")
    if delta is not None and delta > tolerance:
        return placeholder_panel(label, f"no nearby image\ndt {delta:.3f}s")

    image_path = resolve_image_path(run_dir, camera_name, row)
    if image_path is None:
        return placeholder_panel(label, "missing filename")
    if not image_path.exists():
        return placeholder_panel(label, f"missing image\n{image_path.name}")

    try:
        image = Image.open(image_path).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        return placeholder_panel(label, f"unreadable image\n{exc}")

    return add_panel_label(image, label, f"dt {delta:.3f}s")


def build_thermal_panel(label: str, series: SensorSeries, base_ts: float, tolerance: float) -> Image.Image:
    row, delta = optional_nearest_row(series, base_ts)
    if row is None:
        return placeholder_panel(label, "missing CSV/data")
    if delta is not None and delta > tolerance:
        return placeholder_panel(label, f"no nearby frame\ndt {delta:.3f}s")

    frame = row.row.get("frame")
    if frame is None:
        return placeholder_panel(label, "missing frame")

    try:
        frame_array = np.asarray(frame, dtype=np.float32)
        finite_values = frame_array[np.isfinite(frame_array)]
        if finite_values.size == 0:
            return placeholder_panel(label, "invalid frame\nall values are NaN")
        fill_value = float(np.median(finite_values))
        frame_array = np.where(np.isfinite(frame_array), frame_array, fill_value)
        thermal_rgb = frame_to_rgb(frame_array, THERMAL_PIXEL_SIZE)
        image = Image.fromarray(thermal_rgb, mode="RGB")
    except (ValueError, TypeError) as exc:
        return placeholder_panel(label, f"invalid frame\n{exc}")

    return add_panel_label(image, label, f"dt {delta:.3f}s")


def build_camera_grid(
    *,
    run_dir: Path,
    timercam_series: dict[str, SensorSeries],
    thermal_series: dict[str, SensorSeries],
    visual_tolerances: dict[str, float],
    base_ts: float,
) -> Image.Image:
    grid = Image.new("RGB", (CANVAS_WIDTH, GRID_HEIGHT), "#000000")

    for col, (camera_name, label) in enumerate(TIMER_CAMERAS):
        panel = build_timercam_panel(
            run_dir,
            camera_name,
            label,
            timercam_series[camera_name],
            base_ts,
            visual_tolerances[camera_name],
        )
        grid.paste(panel, (col * PANEL_WIDTH, 0))

    for col, (camera_name, label, _) in enumerate(THERMAL_CAMERAS):
        panel = build_thermal_panel(label, thermal_series[camera_name], base_ts, visual_tolerances[camera_name])
        grid.paste(panel, (col * PANEL_WIDTH, PANEL_HEIGHT))

    return grid


def format_dt(delta: float | None) -> str:
    return "n/a" if delta is None else f"{delta:.3f}s"


def format_info_lines(
    *,
    base_name: str,
    base_ts: float,
    distance_row: TimedRow | None,
    distance_delta: float | None,
    pir_row: TimedRow | None,
    pir_delta: float | None,
    annotation_flag: bool,
    annotation_delta: float | None,
    available_series: list[str],
) -> list[str]:
    annotation_text = "True" if annotation_flag else "False"
    annotation_delta_text = "n/a" if annotation_delta is None else f"{annotation_delta:.3f}s"
    distance_text = (
        "Distance: missing"
        if distance_row is None
        else f"Distance: {distance_row.row.get('distance_cm', 'n/a')} cm   ts: {distance_row.timestamp:.6f}   dt: {format_dt(distance_delta)}"
    )
    pir_text = (
        "PIR: missing"
        if pir_row is None
        else (
            f"PIR ts: {pir_row.timestamp:.6f}   dt: {format_dt(pir_delta)}   "
            f"motion: {pir_row.row.get('motion', 'n/a')}   "
            f"presence: {pir_row.row.get('presence', 'n/a')}   "
            f"ambient: {pir_row.row.get('ambient', 'n/a')}"
        )
    )
    return [
        f"Base sensor: {base_name}   timestamp: {base_ts:.6f}",
        f"Available aligned streams: {', '.join(available_series) if available_series else 'none'}",
        distance_text,
        pir_text,
        f"Annotation: {annotation_text}   match_dt: {annotation_delta_text}",
    ]


def compose_frame(
    *,
    run_dir: Path,
    timercam_series: dict[str, SensorSeries],
    thermal_series: dict[str, SensorSeries],
    visual_tolerances: dict[str, float],
    base_ts: float,
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
    canvas.paste(
        build_camera_grid(
            run_dir=run_dir,
            timercam_series=timercam_series,
            thermal_series=thermal_series,
            visual_tolerances=visual_tolerances,
            base_ts=base_ts,
        ),
        (0, 0),
    )
    canvas.paste(build_info_panel(info_lines), (0, GRID_HEIGHT))
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
        (0, GRID_HEIGHT + INFO_HEIGHT),
    )
    return canvas


def pick_base_series(all_series: dict[str, SensorSeries]) -> tuple[str, SensorSeries]:
    non_empty = {name: series for name, series in all_series.items() if series.rows}
    if not non_empty:
        raise ValueError("no usable timestamped streams found")

    fps_by_sensor = {name: estimate_fps(series) for name, series in non_empty.items()}
    positive_fps = {name: fps for name, fps in fps_by_sensor.items() if fps > 0}
    if positive_fps:
        base_name = min(positive_fps, key=positive_fps.get)
    else:
        base_name = min(non_empty, key=lambda name: len(non_empty[name].rows))
    return base_name, non_empty[base_name]


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    output_dir = (args.output_dir if args.output_dir is not None else run_dir / DEFAULT_OUTPUT_DIR_NAME).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    timercam_series = {
        name: load_optional_csv_rows(run_dir / f"{name}.csv", label)
        for name, label in TIMER_CAMERAS
    }
    thermal_series = {
        name: load_optional_thermal_rows(first_existing(run_dir, candidates), label)
        for name, label, candidates in THERMAL_CAMERAS
    }
    distance_series = load_optional_csv_rows(run_dir / "distance.csv", "distance")
    pir_series = load_optional_csv_rows(run_dir / "main_pir.csv", "main_pir")
    annotation_series = load_optional_csv_rows(run_dir / "annotation.csv", "annotation")

    candidate_base_series = {
        **timercam_series,
        **thermal_series,
        "distance": distance_series,
        "main_pir": pir_series,
    }
    base_name, base_series = pick_base_series(candidate_base_series)
    annotation_tolerance = (
        args.annotation_tolerance
        if args.annotation_tolerance is not None
        else max(0.25, median_interval(base_series) / 2.0)
    )
    visual_tolerances = {
        name: auto_match_tolerance(series, args.max_match_delta)
        for name, series in {**timercam_series, **thermal_series}.items()
    }

    print("Sensor FPS:")
    for name, series in candidate_base_series.items():
        print(f"  {name}: {estimate_fps(series):.3f} ({len(series.rows)} rows)")
    print(f"Base sensor: {base_name}")
    print(f"Annotation tolerance: {annotation_tolerance:.3f}s")
    print("Visual match tolerances:")
    for name, tolerance in visual_tolerances.items():
        print(f"  {name}: {tolerance:.3f}s")

    available_series = [name for name, series in candidate_base_series.items() if series.rows]
    frame_total = len(base_series.rows) if args.limit is None else min(len(base_series.rows), args.limit)

    for index, base_row in enumerate(base_series.rows[:frame_total], start=1):
        base_ts = base_row.timestamp
        distance_row, distance_delta = optional_nearest_row(distance_series, base_ts)
        pir_row, pir_delta = optional_nearest_row(pir_series, base_ts)
        annotation_flag, annotation_delta = annotation_value(annotation_series, base_ts, annotation_tolerance)

        distance_history = latest_history(distance_series, distance_row.timestamp if distance_row else base_ts)
        pir_history = latest_history(pir_series, pir_row.timestamp if pir_row else base_ts)
        distance_values, distance_labels = history_values(distance_history, "distance_cm")
        motion_values, motion_labels = history_values(pir_history, "motion")
        presence_values, presence_labels = history_values(pir_history, "presence")
        ambient_values, ambient_labels = history_values(pir_history, "ambient")

        image = compose_frame(
            run_dir=run_dir,
            timercam_series=timercam_series,
            thermal_series=thermal_series,
            visual_tolerances=visual_tolerances,
            base_ts=base_ts,
            info_lines=format_info_lines(
                base_name=base_name,
                base_ts=base_ts,
                distance_row=distance_row,
                distance_delta=distance_delta,
                pir_row=pir_row,
                pir_delta=pir_delta,
                annotation_flag=annotation_flag,
                annotation_delta=annotation_delta,
                available_series=available_series,
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
