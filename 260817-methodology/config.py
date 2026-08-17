from dataclasses import dataclass, field
from pathlib import Path


CAMERA_FILES = {
    "front": "main.csv",
    "back": "thermal2.csv",
    "right": "thermal3.csv",
    "left": "thermal4.csv",
}


@dataclass
class PreprocessingConfig:
    width: int = 32
    height: int = 24
    horizontal_flip: bool = True
    warmup_seconds: float = 60.0
    calibration_low_c: float = 20.0
    calibration_high_c: float = 30.0
    calibration_dirname: str = "calibration"
    outlier_window_frames: int = 15
    outlier_min_periods: int = 5
    outlier_iqr_multiplier: float = 3.0
    outlier_min_deviation_c: float = 0.75
    max_anomalous_fraction: float = 0.10
    # Rectangles are inclusive (x_min, y_min, x_max, y_max).
    interference_masks: dict[str, list[tuple[int, int, int, int]]] = field(
        default_factory=lambda: {name: [] for name in CAMERA_FILES}
    )


@dataclass
class AggregationConfig:
    trim_fraction_each_side: float = 0.10
    trailing_window_seconds: float = 3.0


@dataclass
class FusionConfig:
    epsilon_c: float = 1e-3
    max_alignment_delta_seconds: float = 1.0
    minimum_cameras: int = 4


@dataclass
class RadiantConfig:
    view_factors: dict[str, float] = field(
        default_factory=lambda: {name: 0.25 for name in CAMERA_FILES}
    )
    air_temperature_filename: str = "air_temperature.csv"
    max_air_alignment_delta_seconds: float = 1.0


@dataclass
class SpatialConfig:
    localization_filename: str = "localization.csv"
    max_alignment_delta_seconds: float = 1.0
    grid_size: int = 80
    margin_m: float = 0.5
    length_scale_m: float = 1.0
    signal_std_c: float = 2.0
    noise_std_c: float = 0.20
    max_training_samples: int = 500


@dataclass
class PipelineConfig:
    project_root: Path
    output_root: Path
    camera_files: dict[str, str] = field(default_factory=lambda: dict(CAMERA_FILES))
    preprocessing: PreprocessingConfig = field(default_factory=PreprocessingConfig)
    aggregation: AggregationConfig = field(default_factory=AggregationConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    radiant: RadiantConfig = field(default_factory=RadiantConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)


def get_config() -> PipelineConfig:
    project_root = Path(__file__).resolve().parent
    return PipelineConfig(
        project_root=project_root,
        output_root=project_root / "outputs",
    )
