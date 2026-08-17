from dataclasses import dataclass
from pathlib import Path
import warnings

import numpy as np
import pandas as pd

from config import PipelineConfig, PreprocessingConfig


@dataclass
class CameraFrames:
    name: str
    timestamps: np.ndarray
    frames_c: np.ndarray
    anomalous_fraction: np.ndarray


def _pixel_columns(data: pd.DataFrame, expected_pixels: int) -> list[str]:
    columns = [column for column in data.columns if column.startswith("p") and column[1:].isdigit()]
    columns.sort(key=lambda column: int(column[1:]))
    if len(columns) != expected_pixels:
        raise ValueError(
            f"expected {expected_pixels} thermal columns p0..p{expected_pixels - 1}, "
            f"found {len(columns)}"
        )
    expected = list(range(expected_pixels))
    actual = [int(column[1:]) for column in columns]
    if actual != expected:
        raise ValueError("thermal pixel columns are incomplete or duplicated")
    return columns


def load_thermal_csv(path: Path, settings: PreprocessingConfig) -> tuple[np.ndarray, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"thermal input not found: {path}")

    data = pd.read_csv(path)
    if "timestamp" not in data.columns:
        raise ValueError(f"timestamp column is missing from {path}")

    expected_pixels = settings.width * settings.height
    pixels = _pixel_columns(data, expected_pixels)
    timestamps = pd.to_numeric(data["timestamp"], errors="coerce").to_numpy(dtype=float)
    values = data[pixels].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    valid_time = np.isfinite(timestamps)
    if not valid_time.any():
        raise ValueError(f"no valid timestamps found in {path}")

    timestamps = timestamps[valid_time]
    values = values[valid_time]
    order = np.argsort(timestamps, kind="stable")
    frames = values[order].reshape(-1, settings.height, settings.width)
    if settings.horizontal_flip:
        frames = frames[:, :, ::-1]
    return timestamps[order], frames


def _find_calibration_files(
    input_dir: Path,
    camera_name: str,
    source_stem: str,
    settings: PreprocessingConfig,
) -> tuple[Path | None, Path | None]:
    calibration_dir = input_dir / settings.calibration_dirname
    low_label = f"{settings.calibration_low_c:g}"
    high_label = f"{settings.calibration_high_c:g}"
    names = (camera_name, source_stem)

    def find(label: str) -> Path | None:
        for name in names:
            candidate = calibration_dir / f"{name}_{label}.csv"
            if candidate.is_file():
                return candidate
        return None

    return find(low_label), find(high_label)


def _apply_two_point_calibration(
    frames: np.ndarray,
    input_dir: Path,
    camera_name: str,
    source_stem: str,
    settings: PreprocessingConfig,
) -> tuple[np.ndarray, bool]:
    low_path, high_path = _find_calibration_files(
        input_dir, camera_name, source_stem, settings
    )
    if low_path is None or high_path is None:
        warnings.warn(
            f"[{camera_name}] two-point calibration files are unavailable; "
            "using raw sensor temperatures (identity calibration)",
            stacklevel=2,
        )
        return frames.copy(), False

    _, low_frames = load_thermal_csv(low_path, settings)
    _, high_frames = load_thermal_csv(high_path, settings)
    measured_low = np.nanmedian(low_frames, axis=0)
    measured_high = np.nanmedian(high_frames, axis=0)
    denominator = measured_high - measured_low
    usable = np.isfinite(denominator) & (np.abs(denominator) >= 0.25)

    gain = np.ones_like(measured_low)
    offset = np.zeros_like(measured_low)
    gain[usable] = (
        settings.calibration_high_c - settings.calibration_low_c
    ) / denominator[usable]
    offset[usable] = settings.calibration_low_c - gain[usable] * measured_low[usable]

    unusable_count = int((~usable).sum())
    if unusable_count:
        warnings.warn(
            f"[{camera_name}] {unusable_count} calibration pixels had an invalid response; "
            "identity correction was retained for them",
            stacklevel=2,
        )
    return frames * gain[None, :, :] + offset[None, :, :], True


def _filter_running_outliers(
    frames: np.ndarray, settings: PreprocessingConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    flat = frames.reshape(len(frames), -1)
    frame_table = pd.DataFrame(flat)
    rolling = frame_table.rolling(
        window=settings.outlier_window_frames,
        min_periods=settings.outlier_min_periods,
    )
    median = rolling.median().shift(1).to_numpy(dtype=float)
    q1 = rolling.quantile(0.25).shift(1).to_numpy(dtype=float)
    q3 = rolling.quantile(0.75).shift(1).to_numpy(dtype=float)
    iqr = q3 - q1
    deviation_limit = np.maximum(
        settings.outlier_iqr_multiplier * iqr,
        settings.outlier_min_deviation_c,
    )

    has_baseline = np.isfinite(median)
    anomalies = (~np.isfinite(flat)) | (
        has_baseline & (np.abs(flat - median) > deviation_limit)
    )
    anomalous_fraction = anomalies.mean(axis=1)
    valid_frames = anomalous_fraction <= settings.max_anomalous_fraction

    filtered = flat.copy()
    pixel_median = frame_table.median(axis=0, skipna=True).to_numpy(dtype=float)
    finite_values = flat[np.isfinite(flat)]
    overall_median = float(np.median(finite_values)) if finite_values.size else 0.0
    pixel_median = np.where(np.isfinite(pixel_median), pixel_median, overall_median)
    replacement = np.where(np.isfinite(median), median, pixel_median[None, :])
    filtered[anomalies] = replacement[anomalies]
    return filtered.reshape(frames.shape), anomalous_fraction, valid_frames


def _apply_interference_mask(
    frames: np.ndarray,
    camera_name: str,
    settings: PreprocessingConfig,
) -> np.ndarray:
    result = frames.copy()
    rectangles = settings.interference_masks.get(camera_name, [])
    if not rectangles:
        warnings.warn(
            f"[{camera_name}] no characterized robot/enclosure interference mask is configured",
            stacklevel=2,
        )
    for x_min, y_min, x_max, y_max in rectangles:
        if not (0 <= x_min <= x_max < settings.width and 0 <= y_min <= y_max < settings.height):
            raise ValueError(f"invalid {camera_name} interference mask rectangle")
        result[:, y_min : y_max + 1, x_min : x_max + 1] = np.nan
    return result


def _save_preprocessed(camera: CameraFrames, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    flat = camera.frames_c.reshape(len(camera.frames_c), -1)
    columns = [f"p{i}" for i in range(flat.shape[1])]
    data = pd.DataFrame(flat, columns=columns)
    data.insert(0, "anomalous_fraction", camera.anomalous_fraction)
    data.insert(0, "timestamp", camera.timestamps)
    data.to_csv(output_dir / f"{camera.name}.csv", index=False)


def run_preprocessing(
    input_dir: Path,
    output_dir: Path,
    config: PipelineConfig,
) -> dict[str, CameraFrames]:
    results: dict[str, CameraFrames] = {}
    settings = config.preprocessing

    for camera_name, filename in config.camera_files.items():
        path = input_dir / filename
        timestamps, frames = load_thermal_csv(path, settings)
        original_count = len(frames)

        warmup_end = timestamps[0] + settings.warmup_seconds
        after_warmup = timestamps >= warmup_end
        if not after_warmup.any():
            raise ValueError(
                f"[{camera_name}] no frames remain after the "
                f"{settings.warmup_seconds:g} s warm-up exclusion"
            )
        timestamps = timestamps[after_warmup]
        frames = frames[after_warmup]

        frames, calibrated = _apply_two_point_calibration(
            frames, input_dir, camera_name, Path(filename).stem, settings
        )
        frames, anomalous_fraction, valid_frames = _filter_running_outliers(frames, settings)
        rejected_count = int((~valid_frames).sum())
        frames = _apply_interference_mask(frames[valid_frames], camera_name, settings)
        camera = CameraFrames(
            name=camera_name,
            timestamps=timestamps[valid_frames],
            frames_c=frames,
            anomalous_fraction=anomalous_fraction[valid_frames],
        )
        results[camera_name] = camera
        _save_preprocessed(camera, output_dir / "preprocessed")
        print(
            f"  {camera_name}: loaded={original_count}, warm-up removed="
            f"{int((~after_warmup).sum())}, rejected={rejected_count}, "
            f"retained={len(camera.frames_c)}, calibrated={calibrated}"
        )

    return results
