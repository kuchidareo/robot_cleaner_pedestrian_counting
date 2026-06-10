#!/usr/bin/env python3
import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter, FuncAnimation


def load_points(csv_file: Path) -> tuple[list[float], list[float], list[float]]:
    x, y, angles = [], [], []
    with csv_file.open(newline="") as source:
        for row in csv.DictReader(source):
            x.append(float(row["x"]))
            y.append(float(row["y"]))
            angles.append(float(row["angle_degrees"]))
    if not x:
        raise ValueError(f"No trajectory points found in {csv_file}")
    return x, y, angles


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an S40C trajectory as an MP4 video")
    parser.add_argument("csv_file", nargs="?", default="logs/s40c_trajectory.csv")
    parser.add_argument("--output", default="visualization/s40c_trajectory.mp4")
    parser.add_argument("--duration", type=float, default=30.0, help="Video duration in seconds")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    x, y, angles = load_points(Path(args.csv_file))
    frame_count = max(2, round(args.duration * args.fps))
    point_for_frame = [round(i * (len(x) - 1) / (frame_count - 1)) for i in range(frame_count)]

    fig, ax = plt.subplots(figsize=(8, 8), facecolor="#f3efe5")
    ax.set_facecolor("#f3efe5")
    ax.set_aspect("equal", adjustable="box")
    margin = max(max(x) - min(x), max(y) - min(y)) * 0.05
    ax.set_xlim(min(x) - margin, max(x) + margin)
    ax.set_ylim(min(y) - margin, max(y) + margin)
    ax.set_title("Xiaomi S40C Cleaning Trajectory", fontsize=16, weight="bold")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.grid(color="#1f2926", alpha=0.10, linewidth=0.7)

    trail, = ax.plot([], [], color="#147d75", linewidth=2.2, alpha=0.9)
    vacuum, = ax.plot([], [], marker="o", markersize=9, color="#e4572e", markeredgecolor="#1f2926")
    direction, = ax.plot([], [], color="#1f2926", linewidth=2)
    counter = ax.text(0.02, 0.98, "", transform=ax.transAxes, va="top", fontsize=10)

    arrow_length = max(max(x) - min(x), max(y) - min(y)) * 0.025

    def update(frame: int):
        index = point_for_frame[frame]
        trail.set_data(x[: index + 1], y[: index + 1])
        vacuum.set_data([x[index]], [y[index]])
        angle = math.radians(angles[index])
        direction.set_data(
            [x[index], x[index] + arrow_length * math.cos(angle)],
            [y[index], y[index] + arrow_length * math.sin(angle)],
        )
        counter.set_text(f"Point {index + 1:,} / {len(x):,}")
        return trail, vacuum, direction, counter

    animation = FuncAnimation(fig, update, frames=frame_count, interval=1000 / args.fps, blit=True)
    writer = FFMpegWriter(fps=args.fps, codec="libx264", bitrate=3000, extra_args=["-pix_fmt", "yuv420p"])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    animation.save(args.output, writer=writer, dpi=150)
    plt.close(fig)
    print(f"Saved {frame_count} frames to {args.output}")


if __name__ == "__main__":
    main()
