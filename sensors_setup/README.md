# Sensor Setup

The active setup contains four MLX90640 thermal arrays. TimerCams, the distance
sensor, the TCA9548A multiplexer, and the PIR sensor are no longer used.

| Device | Direction | Connection | I2C pins | WebSocket port |
| --- | --- | --- | --- | --- |
| MainController / Thermal 1 | Front | Direct pins | SDA 32, SCL 33 | 81 |
| ThermalCamera2 | Back | Cable / Thermal Hat | SDA 0, SCL 26 | 84 |
| ThermalCamera3 | Right | Direct pins | SDA 32, SCL 33 | 85 |
| ThermalCamera4 | Left | Cable / Thermal Hat | SDA 0, SCL 26 | 86 |

MainController also sends its built-in IMU measurements. Its binary packet is:

1. `uint16 cols`, `uint16 rows`
2. Six `float32` IMU values: gyro X/Y/Z and acceleration X/Y/Z
3. 768 `float32` thermal values for the 32 x 24 frame

ThermalCamera2-4 send only the dimensions and 768 thermal values.

Run the collector from the repository root:

```bash
venv/bin/python sensors_setup/server.py
```

Each run is saved under `sensors_setup/out/<timestamp>/`:

```text
main.csv
main_imu.csv
thermal2.csv
thermal3.csv
thermal4.csv
annotation.csv
```

To create timestamp-aligned 2x2 thermal JPEGs:

```bash
venv/bin/python sensors_setup/aggregate_aligned_jpegs.py \
  --run-dir sensors_setup/out/<timestamp>
```

Missing thermal streams or frames without a match within 1 second are shown as
black panels.
