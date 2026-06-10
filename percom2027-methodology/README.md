# PerCom 2027 Methodology

This directory contains a simple, deterministic processing pipeline for the
robot cleaner pedestrian-sensing experiments. It combines PIR, distance, IMU,
thermal-array, TimerCam, and manual annotation data.

The project intentionally uses rule-based methods only. It does not use machine
learning, camera calibration, cross-camera identity matching, or simulation.

`run_all.py` is the only executable entry point.

## Project Structure

```text
percom2027-methodology/
├── analysis/
│   ├── availability_analysis.py
│   ├── prediction_plot.py
│   └── score_plot.py
├── core/
│   ├── activity_detector.py
│   ├── data_loader.py
│   ├── motion_estimator.py
│   ├── pedestrian_prediction.py
│   └── scheduler.py
├── data/
│   └── controlled_1person/
├── figures/
├── simulation/
│   └── full_pipeline.py          # unused
├── README.md
└── run_all.py
```

## Running the Pipeline

Use the Python virtual environment in the parent repository:

```bash
cd percom2027-methodology
../venv/bin/python run_all.py --data-dir data/controlled_1person
```

The `--data-dir` argument must point to one experiment directory. Its default
value is `data/controlled_1person`.

The pipeline runs these steps directly:

```text
load and align sensor data
        |
        v
compute activity score
        |
        v
compute motion score
        |
        v
compute reliability and availability
        |
        v
save score CSV and plots
        |
        v
detect and track thermal hot regions
        |
        v
save synchronized thermal/TimerCam plots
```

The `simulation/` directory is not imported or executed.

## Experiment Data

An experiment directory is expected to contain:

```text
annotation.csv
distance.csv
main.csv
main_imu.csv
main_pir.csv
thermal2.csv
thermal3.csv
thermal4.csv
timercam1.csv
timercam2.csv
timercam3.csv
timercam4.csv
timercam1/*.jpg
timercam2/*.jpg
timercam3/*.jpg
timercam4/*.jpg
```

`main.csv` is Thermal Camera 1. The main controller also produces
`main_imu.csv` and `main_pir.csv`.

## Sensor Data Alignment

`core/data_loader.py` builds one dataframe from:

- `main_pir.csv`
- `distance.csv`
- `main_imu.csv`
- `annotation.csv`

The PIR data is the base timeline. Distance and IMU rows are aligned to it with
nearest-timestamp matching using `pandas.merge_asof`.

The resulting canonical columns are:

```text
relative_time_s
pir_detected
distance
gyro_z
annotation
```

Manual annotations are not used to calculate any score. Each positive
annotation timestamp is assigned to its nearest sample on the PIR timeline.
Every other sample is marked `False`.

## Score Pipeline

### Activity Score

`ActivityDetector` returns either `0` or `1`.

```text
distance_change = abs(current_distance - previous_distance)
distance_activity = distance_change > 10
activity_score = pir_detected OR distance_activity
```

Numeric PIR values greater than zero are treated as active.

### Motion Score

`MotionEstimator` uses the absolute Z-axis gyroscope value:

```text
motion_score = 1 - abs(gyro_z) / 2.0
```

The result is clamped to `[0, 1]` and rounded to two decimal places. A score
near `1` means that the robot is relatively stable.

### Reliability Score

`Scheduler` combines activity and motion:

```text
reliability_score =
    0.6 * activity_score
    + 0.4 * motion_score
```

A sample is available when:

```text
reliability_score > 0.7
```

Availability is the fraction of available samples in the processed dataframe.

## Thermal Frame Reconstruction

Each thermal CSV row has this format:

```text
timestamp,p0,p1,...,p767
```

The 768 values are temperatures in degrees Celsius. They are reconstructed as
a `24 x 32` NumPy array:

```python
pixels = row.filter(regex=r"^p\d+$").to_numpy(dtype=float)
frame = pixels.reshape(24, 32)
```

Pixel order is row-major:

```text
p0   ... p31   -> row 0
p32  ... p63   -> row 1
...
p736 ... p767  -> row 23
```

The loader sorts pixel names numerically, so `p2` is placed before `p10`.

## Thermal Normalization

All four thermal cameras use the same fixed Celsius range:

```text
minimum = 20.0 C
maximum = 28.0 C
```

Normalization is:

```text
normalized = (temperature - 20.0) / (28.0 - 20.0)
```

Values are clipped to `[0, 1]`.

The same `20-28 C` range is used for thermal visualization, making colors
comparable between cameras and between timestamps.

This range was selected because pedestrian regions in the current recording
are generally around `24-27 C`. The sensors observe mixed body/background
pixels, so a person should not be expected to appear at skin temperature such
as `35 C`.

## Thermal Pedestrian Detection

`ThermalPedestrianPredictor` detects connected hot regions without machine
learning.

The default normalized threshold is:

```text
hot_threshold = 0.5
```

With the shared normalization range, this is equivalent to:

```text
24.0 C
```

The detector:

1. Creates a mask of pixels at or above `24 C`.
2. Finds connected components using an 8-neighbor BFS.
3. Calculates each component's area and bounding box.
4. Rejects components outside the configured size limits.
5. Scores a component using its mean normalized temperature.

Default component limits:

```text
minimum area:   12 pixels
maximum area:  220 pixels
minimum width:   2 pixels
minimum height:  2 pixels
maximum width:  20 pixels
maximum height: 20 pixels
```

An isolated anomalous pixel, including a very high sensor value, is ignored
because it cannot satisfy the minimum area and dimensions.

Each accepted detection contains:

```python
{
    "bbox": [x_min, y_min, x_max, y_max],
    "center": [center_x, center_y],
    "area": area,
    "score": score,
    "track_id": track_id,
}
```

Bounding-box coordinates are inclusive.

## Tracking

Tracking is independent for each thermal camera.

For each new frame, a detection is matched to the nearest detection in the
immediately previous frame. The previous track ID is reused when the center
distance is no more than eight thermal pixels.

One previous detection cannot be assigned to multiple current detections. A
new track ID is created when no valid previous match exists.

Track IDs are not matched across cameras.

## Prediction Visualization

Thermal Camera 1 timestamps are the reference timeline. For every Camera 1
frame, `analysis/prediction_plot.py` selects:

- the nearest frame from each thermal camera;
- the nearest JPEG from each TimerCam manifest.

Each output PNG has eight panels:

```text
Thermal Camera 1 | Thermal Camera 2 | Thermal Camera 3 | Thermal Camera 4
TimerCam 1       | TimerCam 2       | TimerCam 3       | TimerCam 4
```

Thermal panels show the fixed `20-28 C` color scale, bounding boxes, track IDs,
and component scores. TimerCam images are visual references only and are not
used by the detector.

## Output

For an experiment named `controlled_1person`, the pipeline writes:

```text
figures/controlled_1person/
├── processed_scores.csv
├── activity_score.png
├── motion_score.png
├── reliability_score.png
├── scores_overview.png
└── prediction/
    ├── frame_000000.png
    ├── frame_000001.png
    └── ...
```

`processed_scores.csv` contains:

```text
relative_time_s
pir_detected
distance
gyro_z
annotation
activity_score
motion_score
reliability_score
available
```

## Dependencies

The current implementation requires:

- Python 3.10 or newer
- NumPy
- pandas
- matplotlib
- Pillow

These packages are installed in the parent repository's `venv`.

## Current Limitations

- Thermal thresholds and component limits are fixed rule-based parameters.
- Static hot objects may be detected as pedestrians.
- A person represented by fewer than 12 hot pixels will be rejected.
- Tracks only survive consecutive-frame matching.
- There is no cross-camera identity association.
- TimerCam images are used only for visual inspection.
- Manual annotations are loaded but do not affect scoring or prediction.
