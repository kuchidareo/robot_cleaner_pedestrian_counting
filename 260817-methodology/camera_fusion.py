from pathlib import Path

import numpy as np
import pandas as pd

from config import PipelineConfig


def _align_camera(
    timeline: pd.DataFrame,
    camera_data: pd.DataFrame,
    camera_name: str,
    tolerance_seconds: float,
) -> pd.DataFrame:
    values = camera_data[["timestamp", "aggregated_temperature_c"]].copy()
    values = values.rename(
        columns={"aggregated_temperature_c": f"T_{camera_name}_c"}
    ).sort_values("timestamp")
    return pd.merge_asof(
        timeline.sort_values("timestamp"),
        values,
        on="timestamp",
        direction="nearest",
        tolerance=tolerance_seconds,
    )


def run_camera_fusion(
    aggregated: dict[str, pd.DataFrame],
    output_dir: Path,
    config: PipelineConfig,
) -> pd.DataFrame:
    if "front" not in aggregated:
        raise ValueError("front camera is required as the fusion timeline")

    timeline = aggregated["front"][["timestamp"]].copy()
    for camera_name in config.camera_files:
        timeline = _align_camera(
            timeline,
            aggregated[camera_name],
            camera_name,
            config.fusion.max_alignment_delta_seconds,
        )

    temperature_columns = [f"T_{name}_c" for name in config.camera_files]
    values = timeline[temperature_columns].to_numpy(dtype=float)
    available_count = np.isfinite(values).sum(axis=1)
    with np.errstate(invalid="ignore"):
        consensus = np.nanmean(values, axis=1)

    weights = np.where(
        np.isfinite(values),
        1.0 / (np.abs(values - consensus[:, None]) + config.fusion.epsilon_c),
        0.0,
    )
    weight_sum = weights.sum(axis=1)
    fused = np.divide(
        np.nansum(weights * values, axis=1),
        weight_sum,
        out=np.full(len(values), np.nan),
        where=weight_sum > 0,
    )

    result = timeline.copy()
    result["camera_mean_c"] = consensus
    for index, camera_name in enumerate(config.camera_files):
        result[f"weight_{camera_name}"] = weights[:, index]
    result["T_fused_c"] = fused
    result["available_cameras"] = available_count
    result = result[
        result["available_cameras"] >= config.fusion.minimum_cameras
    ].reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "camera_fusion.csv", index=False)
    print(
        f"  retained {len(result)} synchronized samples requiring at least "
        f"{config.fusion.minimum_cameras} cameras"
    )
    return result
