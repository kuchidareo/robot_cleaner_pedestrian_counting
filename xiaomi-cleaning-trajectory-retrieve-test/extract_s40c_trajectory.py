#!/usr/bin/env python3
import argparse
import base64
import csv
import json
from pathlib import Path

from vacuum_map_parser_base.config.color import ColorsPalette
from vacuum_map_parser_base.config.drawable import Drawable
from vacuum_map_parser_base.config.image_config import ImageConfig
from vacuum_map_parser_base.config.size import Sizes
from vacuum_map_parser_xiaomi.map_data_parser import XiaomiMapDataParser


def read_device_id(token_file: Path) -> str:
    for line in token_file.read_text().splitlines():
        if line.startswith("ID:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"No device ID found in {token_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract an S40C cleaning path from a downloaded cloud map")
    parser.add_argument("map_file", nargs="?", default="logs/s40c_map.zlib.enc")
    parser.add_argument("--token-file", default=".token")
    parser.add_argument("--csv", default="logs/s40c_trajectory.csv")
    parser.add_argument("--metadata", default="logs/s40c_trajectory_metadata.json")
    args = parser.parse_args()

    wrapped_map = json.loads(Path(args.map_file).read_bytes())
    encrypted_map = base64.b64decode(wrapped_map["data"]).hex()
    device_id = read_device_id(Path(args.token_file))

    map_parser = XiaomiMapDataParser(
        ColorsPalette(), Sizes(), [Drawable.PATH, Drawable.VACUUM_POSITION], ImageConfig(), []
    )
    unpacked = map_parser.unpack_map(encrypted_map, model="mi.vacuum.e101gb", device_id=device_id)
    map_data = map_parser.parse(unpacked)
    segments = map_data.path.path if map_data.path else []

    csv_path = Path(args.csv)
    metadata_path = Path(args.metadata)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["segment", "point_index", "x", "y", "angle_degrees"])
        for segment_index, segment in enumerate(segments):
            for point_index, point in enumerate(segment):
                writer.writerow([segment_index, point_index, point.x, point.y, point.a])

    metadata = {
        "model": "xiaomi.vacuum.e101gb",
        "map_width": map_data.image.dimensions.width,
        "map_height": map_data.image.dimensions.height,
        "trajectory_segments": len(segments),
        "trajectory_points": sum(len(segment) for segment in segments),
        "vacuum_position": vars(map_data.vacuum_position) if map_data.vacuum_position else None,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f'Extracted {metadata["trajectory_points"]} points to {args.csv}')


if __name__ == "__main__":
    main()
