from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd


FRAME_WIDTH = 32
FRAME_HEIGHT = 24
PIXEL_COUNT = FRAME_WIDTH * FRAME_HEIGHT
THERMAL_MIN_C = 20.0
THERMAL_MAX_C = 28.0
THERMAL_FILES = {
    "camera1": "main.csv",
    "camera2": "thermal2.csv",
    "camera3": "thermal3.csv",
    "camera4": "thermal4.csv",
}


def load_thermal_csv(csv_path):
    path = Path(csv_path)
    data = pd.read_csv(path)

    if "timestamp" not in data.columns:
        raise ValueError(f"Missing timestamp column in {path}")

    pixel_columns = [
        column
        for column in data.columns
        if column.startswith("p") and column[1:].isdigit()
    ]
    pixel_columns.sort(key=lambda column: int(column[1:]))

    if len(pixel_columns) != PIXEL_COUNT:
        raise ValueError(
            f"Expected exactly {PIXEL_COUNT} pixel columns in {path}, "
            f"found {len(pixel_columns)}"
        )

    expected_pixel_numbers = list(range(PIXEL_COUNT))
    pixel_numbers = [int(column[1:]) for column in pixel_columns]
    if pixel_numbers != expected_pixel_numbers:
        raise ValueError(f"Pixel columns in {path} must cover p0 through p767")

    timestamps = pd.to_numeric(data["timestamp"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError(f"Timestamp column in {path} contains non-numeric values")

    frames = data[pixel_columns].to_numpy(dtype=float).reshape(
        -1, FRAME_HEIGHT, FRAME_WIDTH
    )
    return timestamps.to_numpy(dtype=float), frames


def normalize_dataset_frames(
    frames,
    minimum=THERMAL_MIN_C,
    maximum=THERMAL_MAX_C,
):
    if frames.size == 0:
        return np.zeros_like(frames, dtype=float)
    if maximum <= minimum:
        raise ValueError("Thermal normalization maximum must be greater than minimum")

    normalized = (frames - minimum) / (maximum - minimum)
    return np.clip(normalized, 0.0, 1.0)


class ThermalPedestrianPredictor:
    def __init__(
        self,
        hot_threshold=0.5,
        min_area=12,
        max_area=220,
        min_width=2,
        min_height=2,
        max_width=20,
        max_height=20,
        tracking_distance=8,
    ):
        self.hot_threshold = hot_threshold
        self.min_area = min_area
        self.max_area = max_area
        self.min_width = min_width
        self.min_height = min_height
        self.max_width = max_width
        self.max_height = max_height
        self.tracking_distance = tracking_distance

    @staticmethod
    def _component_pixels(mask, start_y, start_x, visited):
        queue = deque([(start_y, start_x)])
        visited[start_y, start_x] = True
        pixels = []

        while queue:
            y, x = queue.popleft()
            pixels.append((y, x))

            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbor_y = y + dy
                    neighbor_x = x + dx
                    if not (
                        0 <= neighbor_y < mask.shape[0]
                        and 0 <= neighbor_x < mask.shape[1]
                    ):
                        continue
                    if visited[neighbor_y, neighbor_x] or not mask[
                        neighbor_y, neighbor_x
                    ]:
                        continue
                    visited[neighbor_y, neighbor_x] = True
                    queue.append((neighbor_y, neighbor_x))

        return pixels

    def detect_frame(self, norm_frame):
        frame = np.asarray(norm_frame, dtype=float)
        if frame.shape != (FRAME_HEIGHT, FRAME_WIDTH):
            raise ValueError(
                f"Expected normalized frame shape {(FRAME_HEIGHT, FRAME_WIDTH)}, "
                f"got {frame.shape}"
            )

        hot_mask = np.isfinite(frame) & (frame >= self.hot_threshold)
        visited = np.zeros(hot_mask.shape, dtype=bool)
        detections = []

        for y in range(FRAME_HEIGHT):
            for x in range(FRAME_WIDTH):
                if visited[y, x] or not hot_mask[y, x]:
                    continue

                pixels = self._component_pixels(hot_mask, y, x, visited)
                area = len(pixels)
                ys = np.fromiter((pixel_y for pixel_y, _ in pixels), dtype=int)
                xs = np.fromiter((pixel_x for _, pixel_x in pixels), dtype=int)

                x_min = int(xs.min())
                x_max = int(xs.max())
                y_min = int(ys.min())
                y_max = int(ys.max())
                width = x_max - x_min + 1
                height = y_max - y_min + 1

                if not (
                    self.min_area <= area <= self.max_area
                    and self.min_width <= width <= self.max_width
                    and self.min_height <= height <= self.max_height
                ):
                    continue

                score = float(np.mean(frame[ys, xs]))
                detections.append(
                    {
                        "bbox": [x_min, y_min, x_max, y_max],
                        "center": [
                            round(float(xs.mean()), 3),
                            round(float(ys.mean()), 3),
                        ],
                        "area": area,
                        "score": round(score, 3),
                    }
                )

        detections.sort(key=lambda detection: detection["area"], reverse=True)
        return detections

    def track_sequence(self, norm_frames):
        predictions = []
        previous_detections = []
        next_track_id = 1

        for norm_frame in norm_frames:
            detections = self.detect_frame(norm_frame)
            available_previous = set(range(len(previous_detections)))

            for detection in detections:
                center = np.asarray(detection["center"], dtype=float)
                best_previous_index = None
                best_distance = float("inf")

                for previous_index in available_previous:
                    previous_center = np.asarray(
                        previous_detections[previous_index]["center"], dtype=float
                    )
                    distance = float(np.linalg.norm(center - previous_center))
                    if distance < best_distance:
                        best_distance = distance
                        best_previous_index = previous_index

                if (
                    best_previous_index is not None
                    and best_distance <= self.tracking_distance
                ):
                    detection["track_id"] = previous_detections[
                        best_previous_index
                    ]["track_id"]
                    available_previous.remove(best_previous_index)
                else:
                    detection["track_id"] = next_track_id
                    next_track_id += 1

            predictions.append(detections)
            previous_detections = detections

        return predictions


def run_pedestrian_prediction(data_dir):
    data_path = Path(data_dir)
    print("loading thermal data")

    result = {}
    for camera_name, filename in THERMAL_FILES.items():
        csv_path = data_path / filename
        timestamps, frames = load_thermal_csv(csv_path)
        norm_frames = normalize_dataset_frames(frames)

        print(f"detecting pedestrians for {camera_name}")
        predictor = ThermalPedestrianPredictor()
        predictions = predictor.track_sequence(norm_frames)
        total_detections = sum(len(frame_detections) for frame_detections in predictions)
        print(f"{camera_name}: {len(frames)} frames, {total_detections} detections")

        result[camera_name] = {
            "csv_path": str(csv_path),
            "timestamps": timestamps,
            "frames": frames,
            "norm_frames": norm_frames,
            "predictions": predictions,
        }

    return result
