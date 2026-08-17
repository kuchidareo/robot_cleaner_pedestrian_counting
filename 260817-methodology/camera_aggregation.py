from pathlib import Path

import numpy as np
import pandas as pd

from config import PipelineConfig
from preprocessing import CameraFrames


def _trimmed_mean(frame: np.ndarray, trim_fraction: float) -> float:
    values = np.sort(frame[np.isfinite(frame)])
    if values.size == 0:
        return float("nan")
    trim_count = int(np.floor(values.size * trim_fraction))
    if trim_count * 2 >= values.size:
        return float("nan")
    if trim_count:
        values = values[trim_count:-trim_count]
    return float(values.mean())


def _trailing_time_mean(
    timestamps: np.ndarray,
    values: np.ndarray,
    window_seconds: float,
) -> np.ndarray:
    index = pd.to_datetime(timestamps, unit="s", utc=True)
    series = pd.Series(values, index=index)
    return series.rolling(f"{window_seconds}s", min_periods=1).mean().to_numpy()


def run_camera_aggregation(
    cameras: dict[str, CameraFrames],
    output_dir: Path,
    config: PipelineConfig,
) -> dict[str, pd.DataFrame]:
    settings = config.aggregation
    if not 0 <= settings.trim_fraction_each_side < 0.5:
        raise ValueError("trim_fraction_each_side must be in [0, 0.5)")

    results: dict[str, pd.DataFrame] = {}
    tables: list[pd.DataFrame] = []
    for camera_name, camera in cameras.items():
        frame_temperatures = np.asarray(
            [
                _trimmed_mean(frame, settings.trim_fraction_each_side)
                for frame in camera.frames_c
            ],
            dtype=float,
        )
        aggregated = _trailing_time_mean(
            camera.timestamps,
            frame_temperatures,
            settings.trailing_window_seconds,
        )
        table = pd.DataFrame(
            {
                "timestamp": camera.timestamps,
                "camera": camera_name,
                "trimmed_temperature_c": frame_temperatures,
                "aggregated_temperature_c": aggregated,
            }
        )
        results[camera_name] = table
        tables.append(table)
        print(
            f"  {camera_name}: {len(table)} directional temperatures, "
            f"mean={np.nanmean(aggregated):.2f} C"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.concat(tables, ignore_index=True).to_csv(
        output_dir / "camera_aggregation.csv", index=False
    )
    return results
