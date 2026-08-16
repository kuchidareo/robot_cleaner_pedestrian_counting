#!/usr/bin/env python3
import argparse
import base64
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
    parser.add_argument("--clean-record", default="logs/s40c_clean_record.json")
    parser.add_argument("--timezone", default="Europe/Tallinn")
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
    point_count = sum(len(segment) for segment in segments)

    start_utc = None
    duration_seconds = None
    clean_record_path = Path(args.clean_record)
    if clean_record_path.exists():
        clean_record = json.loads(clean_record_path.read_text())
        history = clean_record.get("history_list", [])
        if history:
            start_utc = datetime.fromtimestamp(history[0]["stime"], timezone.utc)
            duration_seconds = int(history[0]["label"].split("_", 1)[0])

    csv_path = Path(args.csv)
    metadata_path = Path(args.metadata)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "segment", "point_index", "x", "y", "angle_degrees",
            "elapsed_seconds", "timestamp_utc", "timestamp_local",
        ])
        global_index = 0
        for segment_index, segment in enumerate(segments):
            for point_index, point in enumerate(segment):
                elapsed = (
                    duration_seconds * global_index / (point_count - 1)
                    if duration_seconds is not None and point_count > 1 else None
                )
                timestamp_utc = start_utc + timedelta(seconds=elapsed) if start_utc else None
                timestamp_local = timestamp_utc.astimezone(ZoneInfo(args.timezone)) if timestamp_utc else None
                writer.writerow([
                    segment_index, point_index, point.x, point.y, point.a,
                    f"{elapsed:.3f}" if elapsed is not None else "",
                    timestamp_utc.isoformat(timespec="milliseconds") if timestamp_utc else "",
                    timestamp_local.isoformat(timespec="milliseconds") if timestamp_local else "",
                ])
                global_index += 1

    metadata = {
        "model": "xiaomi.vacuum.e101gb",
        "map_width": map_data.image.dimensions.width,
        "map_height": map_data.image.dimensions.height,
        "trajectory_segments": len(segments),
        "trajectory_points": point_count,
        "vacuum_position": vars(map_data.vacuum_position) if map_data.vacuum_position else None,
        "timestamps": {
            "method": "uniform interpolation",
            "start_utc": start_utc.isoformat() if start_utc else None,
            "start_local": start_utc.astimezone(ZoneInfo(args.timezone)).isoformat() if start_utc else None,
            "end_local": (
                (start_utc + timedelta(seconds=duration_seconds)).astimezone(ZoneInfo(args.timezone)).isoformat()
                if start_utc and duration_seconds is not None else None
            ),
            "duration_seconds": duration_seconds,
            "timezone": args.timezone,
            "estimated_interval_seconds": (
                duration_seconds / (point_count - 1)
                if duration_seconds is not None and point_count > 1 else None
            ),
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f'Extracted {metadata["trajectory_points"]} points to {args.csv}')


if __name__ == "__main__":
    main()
