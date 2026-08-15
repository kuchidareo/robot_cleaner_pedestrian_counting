from __future__ import annotations

import argparse
import csv
import statistics
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from transform_thermalarray import frame_to_rgb, iter_frames


THERMAL_PIXEL_SIZE = 20
PANEL_WIDTH = 640
PANEL_HEIGHT = 480
CANVAS_WIDTH = PANEL_WIDTH * 2
CANVAS_HEIGHT = PANEL_HEIGHT * 2 + 90
DEFAULT_RUN_DIR = Path("out/20260330_1434")
DEFAULT_OUTPUT_DIR_NAME = "aligned_aggregate_jpegs"
DEFAULT_MAX_MATCH_DELTA = 1.0

THERMAL_CAMERAS = (
    ("main", "Thermal 1 (Front)", ("main.csv", "thermal_main.csv")),
    ("thermal2", "Thermal 2 (Back)", ("thermal2.csv", "thermal_cam2.csv")),
    ("thermal3", "Thermal 3 (Right)", ("thermal3.csv", "thermal_cam3.csv")),
    ("thermal4", "Thermal 4 (Left)", ("thermal4.csv", "thermal_cam4.csv")),
)

@dataclass(frozen=True)
class TimedFrame:
    timestamp: float
    frame: np.ndarray


@dataclass(frozen=True)
class ThermalSeries:
    frames: list[TimedFrame]
    timestamps: list[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render four timestamp-aligned thermal arrays as JPEG files.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to <run-dir>/aligned_aggregate_jpegs.",
    )
    parser.add_argument(
        "--max-match-delta",
        type=float,
        default=DEFAULT_MAX_MATCH_DELTA,
        help=f"Maximum nearest-frame time difference in seconds. Default: {DEFAULT_MAX_MATCH_DELTA:.1f}.",
    )
    parser.add_argument("--annotation-tolerance", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def empty_series() -> ThermalSeries:
    return ThermalSeries(frames=[], timestamps=[])


def first_existing(run_dir: Path, candidates: tuple[str, ...]) -> Path:
    for filename in candidates:
        path = run_dir / filename
        if path.exists():
            return path
    return run_dir / candidates[0]


def load_thermal_series(csv_path: Path, label: str) -> ThermalSeries:
    if not csv_path.exists():
        print(f"warning: {label} missing: {csv_path}")
        return empty_series()

    try:
        frames = [
            TimedFrame(timestamp=float(timestamp), frame=frame)
            for _, timestamp, frame in iter_frames(csv_path)
        ]
    except (OSError, ValueError) as exc:
        print(f"warning: {label} could not be loaded from {csv_path}: {exc}")
        return empty_series()

    frames.sort(key=lambda item: item.timestamp)
    if not frames:
        print(f"warning: {label} contains no frames: {csv_path}")
    return ThermalSeries(frames=frames, timestamps=[item.timestamp for item in frames])


def estimate_fps(series: ThermalSeries) -> float:
    if len(series.frames) < 2:
        return 0.0
    duration = series.frames[-1].timestamp - series.frames[0].timestamp
    return (len(series.frames) - 1) / duration if duration > 0 else 0.0


def median_interval(series: ThermalSeries) -> float:
    if len(series.frames) < 2:
        return 0.0
    return statistics.median(
        series.timestamps[index + 1] - series.timestamps[index]
        for index in range(len(series.timestamps) - 1)
    )

def nearest_frame(series: ThermalSeries, target_ts: float) -> tuple[TimedFrame | None, float | None]:
    if not series.frames:
        return None, None

    position = bisect_left(series.timestamps, target_ts)
    candidates: list[TimedFrame] = []
    if position < len(series.frames):
        candidates.append(series.frames[position])
    if position > 0:
        candidates.append(series.frames[position - 1])

    frame = min(candidates, key=lambda item: abs(item.timestamp - target_ts))
    return frame, abs(frame.timestamp - target_ts)


def load_annotations(csv_path: Path) -> tuple[list[float], list[bool]]:
    if not csv_path.exists():
        return [], []

    timestamps: list[float] = []
    values: list[bool] = []
    try:
        with csv_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = row.get("timestamp")
                if not timestamp:
                    continue
                timestamps.append(float(timestamp))
                values.append(str(row.get("annotation", "")).strip().lower() == "true")
    except (OSError, ValueError) as exc:
        print(f"warning: annotation could not be loaded from {csv_path}: {exc}")
        return [], []

    ordered = sorted(zip(timestamps, values), key=lambda item: item[0])
    return [item[0] for item in ordered], [item[1] for item in ordered]


def annotation_at(
    timestamps: list[float],
    values: list[bool],
    target_ts: float,
    tolerance: float,
) -> bool:
    if not timestamps:
        return False

    position = bisect_left(timestamps, target_ts)
    candidates = [index for index in (position - 1, position) if 0 <= index < len(timestamps)]
    nearest_index = min(candidates, key=lambda index: abs(timestamps[index] - target_ts))
    return abs(timestamps[nearest_index] - target_ts) <= tolerance and values[nearest_index]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def placeholder_panel(title: str, reason: str) -> Image.Image:
    panel = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), "black")
    draw = ImageDraw.Draw(panel)
    draw.text((16, 14), title, fill="white", font=load_font(24))
    draw.text((16, 50), reason, fill="#aaaaaa", font=load_font(18))
    return panel


def render_thermal_panel(
    title: str,
    series: ThermalSeries,
    target_ts: float,
    max_match_delta: float,
) -> Image.Image:
    timed_frame, delta = nearest_frame(series, target_ts)
    if timed_frame is None:
        return placeholder_panel(title, "Missing thermal data")
    if delta is None or delta > max_match_delta:
        return placeholder_panel(title, f"No frame within {max_match_delta:.1f}s")

    frame = np.asarray(timed_frame.frame, dtype=np.float32)
    finite_values = frame[np.isfinite(frame)]
    if finite_values.size == 0:
        return placeholder_panel(title, "Invalid thermal frame")

    frame = np.where(np.isfinite(frame), frame, float(np.median(finite_values)))
    panel = Image.fromarray(frame_to_rgb(frame, THERMAL_PIXEL_SIZE)).convert("RGB")
    panel = panel.resize((PANEL_WIDTH, PANEL_HEIGHT), Image.Resampling.NEAREST)

    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, PANEL_WIDTH, 62), fill="black")
    draw.text((12, 6), title, fill="white", font=load_font(22))
    draw.text(
        (12, 34),
        f"dt={delta:.3f}s  min={float(np.min(finite_values)):.2f}C  max={float(np.max(finite_values)):.2f}C",
        fill="#dddddd",
        font=load_font(16),
    )
    return panel


def compose_frame(
    thermal_series: dict[str, ThermalSeries],
    base_name: str,
    base_ts: float,
    max_match_delta: float,
    annotation: bool,
) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "black")

    for index, (name, label, _) in enumerate(THERMAL_CAMERAS):
        panel = render_thermal_panel(label, thermal_series[name], base_ts, max_match_delta)
        x = (index % 2) * PANEL_WIDTH
        y = (index // 2) * PANEL_HEIGHT
        canvas.paste(panel, (x, y))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, PANEL_HEIGHT * 2, CANVAS_WIDTH, CANVAS_HEIGHT), fill="#111111")
    draw.text(
        (16, PANEL_HEIGHT * 2 + 12),
        f"Base: {base_name}    timestamp: {base_ts:.6f}    annotation: {annotation}",
        fill="white",
        font=load_font(22),
    )
    return canvas


def pick_base_series(series_by_name: dict[str, ThermalSeries]) -> tuple[str, ThermalSeries]:
    available = {name: series for name, series in series_by_name.items() if series.frames}
    if not available:
        raise ValueError("no thermal frames found in the run directory")

    measured_fps = {name: estimate_fps(series) for name, series in available.items()}
    positive_fps = {name: fps for name, fps in measured_fps.items() if fps > 0}
    if positive_fps:
        base_name = min(positive_fps, key=positive_fps.get)
    else:
        base_name = min(available, key=lambda name: len(available[name].frames))
    return base_name, available[base_name]


def main() -> None:
    args = parse_args()
    if args.max_match_delta < 0:
        raise ValueError("--max-match-delta must be non-negative")
    if args.limit is not None and args.limit < 0:
        raise ValueError("--limit must be non-negative")

    run_dir = args.run_dir.resolve()
    output_dir = (args.output_dir or run_dir / DEFAULT_OUTPUT_DIR_NAME).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    thermal_series = {
        name: load_thermal_series(first_existing(run_dir, candidates), label)
        for name, label, candidates in THERMAL_CAMERAS
    }
    annotation_timestamps, annotation_values = load_annotations(run_dir / "annotation.csv")
    base_name, base_series = pick_base_series(thermal_series)
    annotation_tolerance = (
        args.annotation_tolerance
        if args.annotation_tolerance is not None
        else max(0.25, median_interval(base_series) / 2.0)
    )

    print("Thermal streams:")
    for name, series in thermal_series.items():
        print(f"  {name}: {len(series.frames)} frames, {estimate_fps(series):.3f} FPS")
    print(f"Base stream: {base_name}")
    print(f"Maximum match delta: {args.max_match_delta:.3f}s")

    frame_total = len(base_series.frames)
    if args.limit is not None:
        frame_total = min(frame_total, args.limit)

    for index, base_frame in enumerate(base_series.frames[:frame_total], start=1):
        timestamp = base_frame.timestamp
        image = compose_frame(
            thermal_series=thermal_series,
            base_name=base_name,
            base_ts=timestamp,
            max_match_delta=args.max_match_delta,
            annotation=annotation_at(
                annotation_timestamps,
                annotation_values,
                timestamp,
                annotation_tolerance,
            ),
        )
        image.save(output_dir / f"aggregate_{index:04d}_{timestamp:.6f}.jpg", quality=95)

    print(f"saved {frame_total} aggregate JPEG files to {output_dir}")


if __name__ == "__main__":
    main()
