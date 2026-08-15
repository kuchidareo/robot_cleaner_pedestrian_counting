from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np


FRAME_WIDTH = 32
FRAME_HEIGHT = 24
N_PIXELS = FRAME_WIDTH * FRAME_HEIGHT
DEFAULT_INPUT = Path("out/20260330_1434/main.csv")
DEFAULT_OUTPUT_DIR = Path("out/20260330_1434/main_thermal_jpegs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert thermal CSV frames into JPEG files using per-frame min/max "
            "normalization and a blue-to-red color map."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Path to thermal CSV file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for output JPEG files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--pixel-size",
        type=int,
        default=1,
        help="Optional nearest-neighbor enlargement factor for each thermal pixel.",
    )
    return parser.parse_args()


def normalize_frame(frame: np.ndarray) -> np.ndarray:
    frame = frame.astype(np.float32, copy=False)
    min_value = float(np.nanmin(frame))
    max_value = float(np.nanmax(frame))

    if not np.isfinite(min_value) or not np.isfinite(max_value):
        raise ValueError("frame contains only non-finite values")

    if max_value == min_value:
        return np.full(frame.shape, 0.5, dtype=np.float32)

    return (frame - min_value) / (max_value - min_value)


def blue_to_red_rgb(normalized: np.ndarray) -> np.ndarray:
    normalized = np.clip(normalized, 0.0, 1.0)
    red = np.round(normalized * 255.0).astype(np.uint8)
    green = np.zeros_like(red, dtype=np.uint8)
    blue = np.round((1.0 - normalized) * 255.0).astype(np.uint8)
    return np.stack([red, green, blue], axis=-1)


def upscale_pixels(rgb: np.ndarray, pixel_size: int) -> np.ndarray:
    if pixel_size == 1:
        return rgb

    return np.repeat(np.repeat(rgb, pixel_size, axis=0), pixel_size, axis=1)


def frame_to_rgb(frame: np.ndarray, pixel_size: int) -> np.ndarray:
    normalized = normalize_frame(frame)
    rgb = blue_to_red_rgb(normalized)
    return upscale_pixels(rgb, pixel_size)


def write_ppm(path: Path, rgb: np.ndarray) -> None:
    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError(f"expected 3 channels, got {channels}")

    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(rgb.tobytes())


def save_jpeg(rgb: np.ndarray, output_path: Path) -> None:
    if shutil.which("sips") is None:
        raise RuntimeError("sips command not found; cannot convert frames to JPEG")

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ppm_path = temp_dir / "frame.ppm"
        write_ppm(ppm_path, rgb)
        subprocess.run(
            ["sips", "-s", "format", "jpeg", str(ppm_path), "--out", str(output_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def iter_frames(csv_path: Path):
    with csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            raise ValueError(f"{csv_path} is empty")

        expected_columns = N_PIXELS + 1
        if len(header) != expected_columns:
            raise ValueError(
                f"expected {expected_columns} columns, found {len(header)} in {csv_path}"
            )

        for row_index, row in enumerate(reader, start=1):
            if len(row) != expected_columns:
                raise ValueError(
                    f"row {row_index} has {len(row)} columns, expected {expected_columns}"
                )

            timestamp = row[0]
            values = np.asarray(row[1:], dtype=np.float32).reshape(FRAME_HEIGHT, FRAME_WIDTH)
            yield row_index, timestamp, values


def main() -> None:
    args = parse_args()

    if args.pixel_size < 1:
        raise ValueError("--pixel-size must be at least 1")

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    frame_count = 0
    for frame_index, timestamp, frame in iter_frames(input_path):
        rgb = frame_to_rgb(frame, args.pixel_size)
        safe_timestamp = timestamp.replace(".", "_")
        output_path = output_dir / f"frame_{frame_index:04d}_{safe_timestamp}.jpg"
        save_jpeg(rgb, output_path)
        frame_count += 1

    print(f"saved {frame_count} JPEG files to {output_dir}")


if __name__ == "__main__":
    main()
