# RoombaSense Methodology Pipeline

This directory implements the five processing stages described in the RoombaSense methodology.

## Run

Copy one recording produced by `sensors_setup/server.py`:

```bash
mkdir -p 260817-methodology/out
cp -r sensors_setup/out/<timestamp> 260817-methodology/out/
```

The four thermal CSV files are required. A normal copied recording also contains the IMU and annotation files:

```text
main.csv       # front thermal array
thermal2.csv   # back thermal array
thermal3.csv   # right thermal array
thermal4.csv   # left thermal array
main_imu.csv
annotation.csv
```

Run from the repository root with the project virtual environment:

```bash
venv/bin/python 260817-methodology/main.py \
  --input-dir 260817-methodology/out/<timestamp>
```

Results are saved to `260817-methodology/outputs/<timestamp>/`.

## Pipeline

### 1. Sample preprocessing

`preprocessing.py` reconstructs every `p0..p767` row as a `24 x 32` frame and corrects the known horizontal flip. It removes the configurable warm-up period, which defaults to 60 seconds.

```python
frames = values[order].reshape(-1, settings.height, settings.width)
frames = frames[:, :, ::-1]

warmup_end = timestamps[0] + settings.warmup_seconds
after_warmup = timestamps >= warmup_end
```

When two black-body reference files are available, it applies a per-pixel linear correction:

```python
gain[usable] = (
    settings.calibration_high_c - settings.calibration_low_c
) / denominator[usable]
offset[usable] = settings.calibration_low_c - gain[usable] * measured_low[usable]
corrected = frames * gain[None, :, :] + offset[None, :, :]
```

Calibration files are read from `<input-dir>/calibration/`, for example `front_20.csv` and `front_30.csv`. Without them, the program reports that identity calibration is being used.

A causal running median and IQR detect anomalous pixels. Anomalous pixels are replaced by the previous running median, and frames exceeding the configured anomalous-pixel fraction are rejected.

```python
deviation_limit = np.maximum(
    settings.outlier_iqr_multiplier * iqr,
    settings.outlier_min_deviation_c,
)
anomalies = np.abs(flat - median) > deviation_limit
valid_frames = anomalous_fraction <= settings.max_anomalous_fraction
```

Robot/enclosure interference rectangles can be configured in `config.py`. Their pixels are changed to `NaN` before aggregation.

### 2. Per-camera temperature aggregation

`camera_aggregation.py` removes the lowest 10% and highest 10% of valid pixels and averages the remaining 80%.

```python
values = np.sort(frame[np.isfinite(frame)])
trim_count = int(np.floor(values.size * 0.10))
trimmed_temperature = values[trim_count:-trim_count].mean()
```

It then applies a causal 3-second trailing mean using the real timestamps:

```python
aggregated = series.rolling("3s", min_periods=1).mean()
```

The output is one directional temperature per camera and timestamp.

### 3. Multi-camera fusion

`camera_fusion.py` aligns the four cameras by nearest timestamp. It calculates the four-camera mean and the methodology's agreement weights:

```python
consensus = np.nanmean(values, axis=1)
weights = 1.0 / (
    np.abs(values - consensus[:, None]) + config.fusion.epsilon_c
)
T_fused = np.nansum(weights * values, axis=1) / weights.sum(axis=1)
```

By default, a synchronized result is retained only when all four cameras are available.

### 4. Radiant-temperature estimation

`radiant_temperature.py` implements the view-factor-weighted fourth-power equation. Celsius is first converted to Kelvin because fourth-power radiation calculations cannot use Celsius.

```python
temperatures_k = temperatures_c + 273.15
T_radiant_k = np.power(
    np.sum(factors[None, :] * np.power(temperatures_k, 4), axis=1),
    0.25,
)
T_radiant_c = T_radiant_k - 273.15
```

The default view factors are `0.25` for each direction. The calculation uses the four directional temperatures, as specified by the methodology's radiant-temperature equation. `T_fused` is retained as a separate output.

If `<input-dir>/air_temperature.csv` exists, its nearest timestamp is added as `T_air_c`. Otherwise `T_air_c` is left empty and a warning is printed.

### 5. Spatial field reconstruction

`spatial_reconstruction.py` aligns each radiant observation with `(x, y)` from `<input-dir>/localization.csv`.

```python
observations = pd.merge_asof(
    radiant,
    localization,
    on="timestamp",
    direction="nearest",
)
```

It reconstructs the field using Gaussian Process Regression with the Matern 3/2 kernel:

```python
scaled_distance = np.sqrt(3.0) * distance / length_scale
kernel = signal_std_c**2 * (1.0 + scaled_distance) * np.exp(-scaled_distance)
```

The implementation uses NumPy directly and saves the predicted radiant temperature and uncertainty. If `localization.csv` is unavailable, only this final stage is skipped.

## Main outputs

```text
preprocessed/front.csv
preprocessed/back.csv
preprocessed/right.csv
preprocessed/left.csv
camera_aggregation.csv
camera_fusion.csv
radiant_temperature.csv
spatial_observations.csv       # when localization exists
spatial_field.csv              # when localization exists
spatial_temperature.png        # when localization exists
spatial_uncertainty.png        # when localization exists
```

All thresholds, time windows, view factors, calibration settings, masks, and GPR parameters are defined in `config.py`.
