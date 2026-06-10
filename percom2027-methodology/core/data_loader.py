from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


TIME_CANDIDATES = (
    "timestamp",
    "time",
    "datetime",
    "created_at",
    "elapsed_time",
    "relative_time",
    "relative_time_s",
)


def _find_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    lookup = {str(column).strip().lower(): column for column in columns}
    for candidate in candidates:
        match = lookup.get(candidate.lower())
        if match is not None:
            return match
    return None


def _load_timed_csv(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    time_column = _find_column(data.columns, TIME_CANDIDATES)

    if time_column is None:
        data["time_s"] = np.arange(len(data), dtype=float)
        return data

    numeric_time = pd.to_numeric(data[time_column], errors="coerce")
    if numeric_time.notna().all():
        data["time_s"] = numeric_time.astype(float)
        return data

    datetime_time = pd.to_datetime(data[time_column], errors="coerce")
    if datetime_time.notna().all():
        data["time_s"] = datetime_time.astype("int64") / 1_000_000_000
        return data

    raise ValueError(f"Could not convert time column '{time_column}' in {path}")


def _canonical_series(
    data: pd.DataFrame,
    candidates: Iterable[str],
    canonical_name: str,
    source_path: Path,
) -> pd.Series:
    column = _find_column(data.columns, candidates)
    if column is None:
        candidate_text = ", ".join(candidates)
        raise ValueError(
            f"Missing required column '{canonical_name}' in {source_path}. "
            f"Searched for: {candidate_text}"
        )
    return data[column]


def _positive_annotation(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _merge_nearest(base: pd.DataFrame, other: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    right = other[["time_s", *columns]].sort_values("time_s")
    return pd.merge_asof(
        base.sort_values("time_s"),
        right,
        on="time_s",
        direction="nearest",
    )


def load_experiment_dataframe(data_dir) -> pd.DataFrame:
    data_path = Path(data_dir)
    paths = {
        "annotation": data_path / "annotation.csv",
        "distance": data_path / "distance.csv",
        "imu": data_path / "main_imu.csv",
        "pir": data_path / "main_pir.csv",
    }

    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(f"Missing required {name} file: {path}")

    pir = _load_timed_csv(paths["pir"])
    distance = _load_timed_csv(paths["distance"])
    imu = _load_timed_csv(paths["imu"])
    annotation = _load_timed_csv(paths["annotation"])

    pir["pir_detected"] = _canonical_series(
        pir,
        ("motion", "presence", "pir", "detected", "pir_detected"),
        "pir_detected",
        paths["pir"],
    )
    distance["distance"] = pd.to_numeric(
        _canonical_series(
            distance,
            ("distance", "distance_mm", "distance_cm", "range"),
            "distance",
            paths["distance"],
        ),
        errors="coerce",
    )
    imu["gyro_z"] = pd.to_numeric(
        _canonical_series(
            imu,
            ("gyro_z", "gyroscope_z", "gyro_z_dps", "gz", "z"),
            "gyro_z",
            paths["imu"],
        ),
        errors="coerce",
    )
    annotation["annotation_value"] = _canonical_series(
        annotation,
        ("annotation", "label", "event", "true", "is_event"),
        "annotation",
        paths["annotation"],
    ).map(_positive_annotation)

    combined = pir[["time_s", "pir_detected"]].copy()
    combined = _merge_nearest(combined, distance, ["distance"])
    combined = _merge_nearest(combined, imu, ["gyro_z"])
    combined = combined.sort_values("time_s").reset_index(drop=True)

    combined["annotation"] = False
    positive_times = annotation.loc[annotation["annotation_value"], "time_s"].to_numpy()
    if len(combined) and len(positive_times):
        base_times = combined["time_s"].to_numpy()
        for event_time in positive_times:
            nearest_index = int(np.abs(base_times - event_time).argmin())
            combined.at[nearest_index, "annotation"] = True

    start_time = float(combined["time_s"].iloc[0]) if len(combined) else 0.0
    combined["relative_time_s"] = combined["time_s"] - start_time

    return combined[
        ["relative_time_s", "pir_detected", "distance", "gyro_z", "annotation"]
    ]
