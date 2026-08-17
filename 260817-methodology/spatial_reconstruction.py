from pathlib import Path
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import PipelineConfig


def _find_column(data: pd.DataFrame, candidates: tuple[str, ...], label: str) -> str:
    column = next((candidate for candidate in candidates if candidate in data.columns), None)
    if column is None:
        raise ValueError(f"localization data is missing a {label} column")
    return column


def _load_localization(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    timestamp_column = _find_column(
        data, ("timestamp", "time", "datetime", "created_at"), "timestamp"
    )
    x_column = _find_column(
        data, ("x", "x_m", "position_x", "world_x_m"), "x position"
    )
    y_column = _find_column(
        data, ("y", "y_m", "position_y", "world_y_m"), "y position"
    )
    result = data[[timestamp_column, x_column, y_column]].rename(
        columns={timestamp_column: "timestamp", x_column: "x_m", y_column: "y_m"}
    )
    result["timestamp"] = pd.to_numeric(result["timestamp"], errors="coerce")
    result["x_m"] = pd.to_numeric(result["x_m"], errors="coerce")
    result["y_m"] = pd.to_numeric(result["y_m"], errors="coerce")
    return result.dropna().sort_values("timestamp")


def _matern32_kernel(
    first: np.ndarray,
    second: np.ndarray,
    length_scale_m: float,
    signal_std_c: float,
) -> np.ndarray:
    if length_scale_m <= 0 or signal_std_c <= 0:
        raise ValueError("GPR length scale and signal standard deviation must be positive")
    distances = np.sqrt(
        np.maximum(
            np.sum(first * first, axis=1)[:, None]
            + np.sum(second * second, axis=1)[None, :]
            - 2.0 * first @ second.T,
            0.0,
        )
    )
    scaled = np.sqrt(3.0) * distances / length_scale_m
    return signal_std_c**2 * (1.0 + scaled) * np.exp(-scaled)


def _select_training_samples(
    positions: np.ndarray,
    temperatures: np.ndarray,
    max_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(positions) <= max_samples:
        return positions, temperatures
    indices = np.linspace(0, len(positions) - 1, max_samples, dtype=int)
    return positions[indices], temperatures[indices]


def _fit_and_predict_gpr(
    training_xy: np.ndarray,
    training_temperature: np.ndarray,
    query_xy: np.ndarray,
    config: PipelineConfig,
) -> tuple[np.ndarray, np.ndarray]:
    settings = config.spatial
    mean_temperature = float(training_temperature.mean())
    centered = training_temperature - mean_temperature
    covariance = _matern32_kernel(
        training_xy,
        training_xy,
        settings.length_scale_m,
        settings.signal_std_c,
    )
    covariance.flat[:: len(covariance) + 1] += settings.noise_std_c**2 + 1e-8
    try:
        cholesky = np.linalg.cholesky(covariance)
    except np.linalg.LinAlgError as exc:
        raise ValueError("GPR covariance matrix is not numerically stable") from exc

    alpha = np.linalg.solve(cholesky.T, np.linalg.solve(cholesky, centered))
    cross_covariance = _matern32_kernel(
        training_xy,
        query_xy,
        settings.length_scale_m,
        settings.signal_std_c,
    )
    predicted_mean = mean_temperature + cross_covariance.T @ alpha
    projected = np.linalg.solve(cholesky, cross_covariance)
    predicted_variance = np.maximum(
        settings.signal_std_c**2 - np.sum(projected * projected, axis=0),
        0.0,
    )
    return predicted_mean, np.sqrt(predicted_variance)


def _plot_field(field: pd.DataFrame, observations: pd.DataFrame, output_dir: Path) -> None:
    x_values = np.sort(field["x_m"].unique())
    y_values = np.sort(field["y_m"].unique())
    shape = (len(y_values), len(x_values))

    figures = (
        ("predicted_T_radiant_c", "Radiant Temperature (C)", "spatial_temperature.png"),
        ("prediction_std_c", "GPR Uncertainty (C)", "spatial_uncertainty.png"),
    )
    for column, title, filename in figures:
        values = field[column].to_numpy().reshape(shape)
        figure, axis = plt.subplots(figsize=(7, 6))
        image = axis.imshow(
            values,
            origin="lower",
            extent=(x_values[0], x_values[-1], y_values[0], y_values[-1]),
            aspect="equal",
            cmap="inferno" if column == "predicted_T_radiant_c" else "viridis",
        )
        axis.plot(observations["x_m"], observations["y_m"], "w.", markersize=2, alpha=0.5)
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_title(title)
        figure.colorbar(image, ax=axis, label=title)
        figure.tight_layout()
        figure.savefig(output_dir / filename, dpi=160)
        plt.close(figure)


def run_spatial_reconstruction(
    radiant: pd.DataFrame,
    input_dir: Path,
    output_dir: Path,
    config: PipelineConfig,
) -> pd.DataFrame | None:
    localization_path = input_dir / config.spatial.localization_filename
    if not localization_path.is_file():
        warnings.warn(
            f"localization file not found: {localization_path}; spatial reconstruction skipped",
            stacklevel=2,
        )
        return None

    localization = _load_localization(localization_path)
    observations = pd.merge_asof(
        radiant.sort_values("timestamp"),
        localization,
        on="timestamp",
        direction="nearest",
        tolerance=config.spatial.max_alignment_delta_seconds,
    )
    observations = observations.dropna(subset=["x_m", "y_m", "T_radiant_c"]).reset_index(drop=True)
    if len(observations) < 2:
        warnings.warn(
            "fewer than two localized radiant observations; spatial reconstruction skipped",
            stacklevel=2,
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    observations.to_csv(output_dir / "spatial_observations.csv", index=False)
    positions = observations[["x_m", "y_m"]].to_numpy(dtype=float)
    temperatures = observations["T_radiant_c"].to_numpy(dtype=float)
    training_xy, training_temperature = _select_training_samples(
        positions, temperatures, config.spatial.max_training_samples
    )

    minimum = positions.min(axis=0) - config.spatial.margin_m
    maximum = positions.max(axis=0) + config.spatial.margin_m
    maximum = np.where(maximum > minimum, maximum, minimum + 1.0)
    grid_x = np.linspace(minimum[0], maximum[0], config.spatial.grid_size)
    grid_y = np.linspace(minimum[1], maximum[1], config.spatial.grid_size)
    mesh_x, mesh_y = np.meshgrid(grid_x, grid_y)
    query = np.column_stack((mesh_x.ravel(), mesh_y.ravel()))
    mean, standard_deviation = _fit_and_predict_gpr(
        training_xy, training_temperature, query, config
    )
    field = pd.DataFrame(
        {
            "x_m": query[:, 0],
            "y_m": query[:, 1],
            "predicted_T_radiant_c": mean,
            "prediction_std_c": standard_deviation,
        }
    )
    field.to_csv(output_dir / "spatial_field.csv", index=False)
    _plot_field(field, observations, output_dir)
    print(
        f"  reconstructed {len(field)} grid locations from "
        f"{len(training_xy)} training observations"
    )
    return field
