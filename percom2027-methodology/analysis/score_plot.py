from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCORE_COLUMNS = (
    ("activity_score", "Activity Score"),
    ("motion_score", "Motion Score"),
    ("reliability_score", "Reliability Score"),
)


def _validate_columns(data) -> None:
    required = {"relative_time_s", *(column for column, _ in SCORE_COLUMNS)}
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError(f"Dataframe is missing required plot columns: {', '.join(missing)}")


def _save_single_plot(data, output_dir: Path, column: str, title: str) -> None:
    figure, axis = plt.subplots(figsize=(10, 4))
    axis.plot(data["relative_time_s"], data[column], linewidth=1.5)
    axis.set_xlabel("Relative Time (s)")
    axis.set_ylabel(title)
    axis.set_ylim(-0.05, 1.05)
    axis.set_title(title)
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(output_dir / f"{column}.png", dpi=150)
    plt.close(figure)


def save_score_plots(data, output_dir):
    _validate_columns(data)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for column, title in SCORE_COLUMNS:
        _save_single_plot(data, output_path, column, title)

    figure, axis = plt.subplots(figsize=(11, 5))
    for column, title in SCORE_COLUMNS:
        axis.plot(data["relative_time_s"], data[column], label=title, linewidth=1.4)
    axis.set_xlabel("Relative Time (s)")
    axis.set_ylabel("Score")
    axis.set_ylim(-0.05, 1.05)
    axis.set_title("Score Overview")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_path / "scores_overview.png", dpi=150)
    plt.close(figure)
