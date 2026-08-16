#!/usr/bin/env python3
import argparse
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from matplotlib.patches import Rectangle
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


def load_map(map_file: Path, token_file: Path):
    wrapped = json.loads(map_file.read_bytes())
    encrypted = base64.b64decode(wrapped["data"]).hex()
    parser = XiaomiMapDataParser(
        ColorsPalette(), Sizes(), list(Drawable), ImageConfig(), []
    )
    unpacked = parser.unpack_map(
        encrypted, model="mi.vacuum.e101gb", device_id=read_device_id(token_file)
    )
    return parser.parse(unpacked)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a four-panel S40C map overview")
    parser.add_argument("--map", default="logs/s40c_map.zlib.enc")
    parser.add_argument("--token-file", default=".token")
    parser.add_argument("--clean-record", default="logs/s40c_clean_record.json")
    parser.add_argument("--timezone", default="Europe/Tallinn")
    parser.add_argument("--output", default="visualization/s40c_map_overview.png")
    args = parser.parse_args()

    map_data = load_map(Path(args.map), Path(args.token_file))
    segments = map_data.path.path if map_data.path else []
    points = [point for segment in segments for point in segment]
    x = np.array([point.x for point in points], dtype=float)
    y = np.array([point.y for point in points], dtype=float)
    heading = np.array([point.a for point in points], dtype=float)

    step_distance = np.r_[0.0, np.hypot(np.diff(x), np.diff(y))] / 1000.0
    cumulative_distance = np.cumsum(step_distance)
    turn = np.r_[0.0, np.abs((np.diff(heading) + 180.0) % 360.0 - 180.0)]

    clean_record = json.loads(Path(args.clean_record).read_text())
    latest_run = clean_record["history_list"][0]
    start = datetime.fromtimestamp(latest_run["stime"], timezone.utc).astimezone(ZoneInfo(args.timezone))
    duration_seconds = int(latest_run["label"].split("_", 1)[0])
    timestamps = [
        start + timedelta(seconds=duration_seconds * i / (len(points) - 1))
        for i in range(len(points))
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 12), constrained_layout=True)
    fig.suptitle("Xiaomi S40C Cleaning-Run Overview", fontsize=18, fontweight="bold")

    ax = axes[0, 0]
    ax.imshow(map_data.image.data)
    ax.set_title("1. Complete floor map and cleaning trajectory")
    ax.set_axis_off()

    ax = axes[0, 1]
    room_colors = plt.cm.Set2(np.linspace(0, 1, max(len(map_data.rooms), 1)))
    for color, (room_id, room) in zip(room_colors, sorted(map_data.rooms.items())):
        rect = Rectangle(
            (room.x0 / 1000.0, room.y0 / 1000.0),
            (room.x1 - room.x0) / 1000.0,
            (room.y1 - room.y0) / 1000.0,
            facecolor=color,
            edgecolor="black",
            alpha=0.35,
            linewidth=1.5,
        )
        ax.add_patch(rect)
        ax.text(room.pos_x / 1000.0, room.pos_y / 1000.0, f"Room {room_id}",
                ha="center", va="center", fontweight="bold")
    ax.plot(x / 1000.0, y / 1000.0, color="black", linewidth=0.8, alpha=0.7)
    ax.scatter(map_data.charger.x / 1000.0, map_data.charger.y / 1000.0,
               marker="s", s=60, color="#d95f02", label="Dock", zorder=3)
    ax.set_title("2. Room IDs, boundaries, and transitions")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    ax.legend(frameon=False)

    ax = axes[1, 0]
    rgba = np.asarray(map_data.image.data)
    background = np.array([19, 87, 148])
    occupied = np.any(rgba[:, :, :3] != background, axis=2)
    interior = occupied.copy()
    interior[1:-1, 1:-1] &= (
        occupied[:-2, 1:-1] & occupied[2:, 1:-1]
        & occupied[1:-1, :-2] & occupied[1:-1, 2:]
    )
    boundary = occupied & ~interior
    py, px = np.nonzero(boundary)
    ax.scatter(px, rgba.shape[0] - py, s=2, color="black", alpha=0.6)
    ax.set_title("3. Reconstructed map-boundary point cloud")
    ax.set_xlabel("Map X (pixel)")
    ax.set_ylabel("Map Y (pixel)")
    ax.set_aspect("equal")
    ax.grid(alpha=0.15)

    ax = axes[1, 1]
    ax.plot(timestamps, cumulative_distance, color="#1b6ca8", linewidth=1.5,
            label="Cumulative distance")
    ax.set_xlabel(f"Estimated local time ({args.timezone})")
    ax.set_ylabel("Cumulative distance (m)", color="#1b6ca8")
    ax.tick_params(axis="y", labelcolor="#1b6ca8")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=ZoneInfo(args.timezone)))
    ax.tick_params(axis="x", rotation=15)
    turn_ax = ax.twinx()
    turn_ax.plot(timestamps, turn, color="#d95f02", linewidth=0.7, alpha=0.65,
                 label="Turn magnitude")
    turn_ax.set_ylabel("Turn between samples (degrees)", color="#d95f02")
    turn_ax.tick_params(axis="y", labelcolor="#d95f02")
    end = timestamps[-1]
    ax.set_title(
        f"4. Motion metrics ({cumulative_distance[-1]:.1f} m)\n"
        f"{start:%Y-%m-%d %H:%M:%S} - {end:%H:%M:%S}"
    )
    ax.grid(alpha=0.2)
    lines = ax.lines + turn_ax.lines
    ax.legend(lines, [line.get_label() for line in lines], loc="upper left", frameon=False)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
