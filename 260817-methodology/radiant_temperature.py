from pathlib import Path
import warnings

import numpy as np
import pandas as pd

from config import PipelineConfig


KELVIN_OFFSET = 273.15


def _load_air_temperature(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    timestamp_candidates = ("timestamp", "time", "datetime")
    temperature_candidates = (
        "air_temperature_c",
        "temperature_c",
        "air_temp_c",
        "temperature",
    )
    timestamp_column = next(
        (column for column in timestamp_candidates if column in data.columns), None
    )
    temperature_column = next(
        (column for column in temperature_candidates if column in data.columns), None
    )
    if timestamp_column is None or temperature_column is None:
        raise ValueError(
            f"{path} must contain timestamp and air-temperature columns"
        )
    result = data[[timestamp_column, temperature_column]].rename(
        columns={timestamp_column: "timestamp", temperature_column: "T_air_c"}
    )
    result["timestamp"] = pd.to_numeric(result["timestamp"], errors="coerce")
    result["T_air_c"] = pd.to_numeric(result["T_air_c"], errors="coerce")
    return result.dropna().sort_values("timestamp")


def run_radiant_temperature(
    fused: pd.DataFrame,
    input_dir: Path,
    output_dir: Path,
    config: PipelineConfig,
) -> pd.DataFrame:
    result = fused.copy()
    camera_names = list(config.camera_files)
    factors = np.asarray(
        [config.radiant.view_factors[name] for name in camera_names], dtype=float
    )
    if not np.isfinite(factors).all() or (factors < 0).any() or factors.sum() <= 0:
        raise ValueError("view factors must be finite, non-negative, and sum above zero")
    factors = factors / factors.sum()

    temperatures_c = result[
        [f"T_{name}_c" for name in camera_names]
    ].to_numpy(dtype=float)
    temperatures_k = temperatures_c + KELVIN_OFFSET
    if (temperatures_k <= 0).any():
        raise ValueError("directional temperatures must be above absolute zero")
    radiant_k = np.power(
        np.sum(factors[None, :] * np.power(temperatures_k, 4), axis=1),
        0.25,
    )
    result["T_radiant_c"] = radiant_k - KELVIN_OFFSET

    air_path = input_dir / config.radiant.air_temperature_filename
    if air_path.is_file():
        air = _load_air_temperature(air_path)
        result = pd.merge_asof(
            result.sort_values("timestamp"),
            air,
            on="timestamp",
            direction="nearest",
            tolerance=config.radiant.max_air_alignment_delta_seconds,
        )
    else:
        warnings.warn(
            f"air-temperature file not found: {air_path}; T_air_c will be NaN",
            stacklevel=2,
        )
        result["T_air_c"] = np.nan

    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "radiant_temperature.csv", index=False)
    print(
        f"  produced {len(result)} radiant-temperature samples using view factors "
        f"{dict(zip(camera_names, factors.round(3).tolist()))}"
    )
    return result
