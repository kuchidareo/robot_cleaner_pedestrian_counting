from functools import lru_cache
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from PIL import Image

from core.pedestrian_prediction import THERMAL_MAX_C, THERMAL_MIN_C

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


TIME_CANDIDATES = (
    "timestamp",
    "time",
    "datetime",
    "created_at",
    "relative_time",
    "relative_time_s",
)
PATH_CANDIDATES = (
    "filename",
    "file",
    "filepath",
    "path",
    "image",
    "image_path",
)


def _find_column(columns, candidates):
    lookup = {str(column).strip().lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


def to_numeric_timestamps(timestamps):
    array = np.asarray(timestamps)
    if np.issubdtype(array.dtype, np.number):
        return array.astype(float, copy=False)

    values = pd.Series(timestamps)
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return numeric.to_numpy(dtype=float)

    datetimes = pd.to_datetime(values, errors="coerce")
    if datetimes.notna().all():
        return datetimes.astype("int64").to_numpy(dtype=float) / 1_000_000_000

    raise ValueError("Could not convert timestamps to numeric values")


def find_nearest_index(timestamps, target_timestamp):
    numeric_timestamps = to_numeric_timestamps(timestamps)
    if len(numeric_timestamps) == 0:
        raise ValueError("Cannot find nearest index in an empty timestamp array")
    target = to_numeric_timestamps([target_timestamp])[0]
    return int(np.argmin(np.abs(numeric_timestamps - target)))


def load_timercam_manifest(csv_path, image_dir):
    manifest_path = Path(csv_path)
    image_directory = Path(image_dir)
    data = pd.read_csv(manifest_path)

    timestamp_column = _find_column(data.columns, TIME_CANDIDATES)
    if timestamp_column is None:
        raise ValueError(f"No timestamp-like column found in {manifest_path}")

    path_column = _find_column(data.columns, PATH_CANDIDATES)
    if path_column is None:
        for column in data.columns:
            values = data[column].astype(str)
            if values.str.contains(r"\.(jpg|jpeg|png)$", case=False, regex=True).any():
                path_column = column
                break
    if path_column is None:
        raise ValueError(f"No image filename/path column found in {manifest_path}")

    timestamps = to_numeric_timestamps(data[timestamp_column])
    image_paths = []
    for manifest_value in data[path_column].astype(str):
        image_path = Path(manifest_value)
        if not image_path.is_absolute():
            image_path = image_directory / image_path
        image_paths.append(str(image_path.resolve()))

    return {"timestamps": timestamps, "image_paths": image_paths}


@lru_cache(maxsize=128)
def _load_rgb_image(image_path):
    with Image.open(image_path) as image:
        return np.asarray(image.convert("RGB"))


def _draw_thermal_panel(axis, camera_data, frame_index, camera_number):
    frame = camera_data["frames"][frame_index]

    axis.imshow(
        frame,
        cmap="inferno",
        origin="upper",
        vmin=THERMAL_MIN_C,
        vmax=THERMAL_MAX_C,
    )
    axis.set_title(f"Thermal Camera {camera_number}")
    axis.set_xlim(-0.5, 31.5)
    axis.set_ylim(23.5, -0.5)

    for detection in camera_data["predictions"][frame_index]:
        x_min, y_min, x_max, y_max = detection["bbox"]
        rectangle = Rectangle(
            (x_min, y_min),
            x_max - x_min + 1,
            y_max - y_min + 1,
            fill=False,
            linewidth=2,
        )
        axis.add_patch(rectangle)
        axis.text(
            x_min,
            max(0, y_min - 1),
            f"ID {detection['track_id']} / {detection['score']:.3f}",
            fontsize=8,
            verticalalignment="top",
        )


def save_prediction_plots(prediction_result, data_dir, output_dir):
    data_path = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timercam_manifests = {
        camera_number: load_timercam_manifest(
            data_path / f"timercam{camera_number}.csv",
            data_path / f"timercam{camera_number}",
        )
        for camera_number in range(1, 5)
    }

    reference_timestamps = to_numeric_timestamps(
        prediction_result["camera1"]["timestamps"]
    )
    total_frames = len(reference_timestamps)
    print(f"saving {total_frames} prediction plots")

    for output_index, reference_timestamp in enumerate(reference_timestamps):
        figure, axes = plt.subplots(2, 4, figsize=(16, 8))
        figure.suptitle(f"Thermal Predictions at {reference_timestamp:.6f}")

        for camera_number in range(1, 5):
            camera_name = f"camera{camera_number}"
            camera_data = prediction_result[camera_name]
            thermal_index = find_nearest_index(
                camera_data["timestamps"], reference_timestamp
            )
            _draw_thermal_panel(
                axes[0, camera_number - 1],
                camera_data,
                thermal_index,
                camera_number,
            )

            manifest = timercam_manifests[camera_number]
            image_index = find_nearest_index(
                manifest["timestamps"], reference_timestamp
            )
            image_path = manifest["image_paths"][image_index]
            if not Path(image_path).is_file():
                raise ValueError(f"TimerCam image does not exist: {image_path}")
            axes[1, camera_number - 1].imshow(_load_rgb_image(image_path))
            axes[1, camera_number - 1].set_title(f"TimerCam {camera_number}")
            axes[1, camera_number - 1].axis("off")

        figure.tight_layout(rect=(0, 0, 1, 0.96))
        figure.savefig(
            output_path / f"frame_{output_index:06d}.png",
            dpi=100,
        )
        plt.close(figure)

        if (output_index + 1) % 50 == 0 or output_index + 1 == total_frames:
            print(f"saved prediction plots: {output_index + 1}/{total_frames}")
