# Robot Cleaner Pedestrian Counting

This repository contains sensor experiments for pedestrian detection around a
robot cleaner and an experimental workflow for retrieving the cleaning
trajectory of a Xiaomi Robot Vacuum S40C.

## Sensors

The main controller records:

- front and rear thermal arrays
- front PIR sensor
- front distance sensor
- gyroscope data

For the thermal sensor placement, Thermal 3 is on the right and Thermal 4 is
on the left.

## Xiaomi S40C trajectory

The tested vacuum is:

```text
MODEL: xiaomi.vacuum.e101gb
```

Direct local access with `python-miio` is not reliable for this model. The
vacuum responds to miIO discovery, but authenticated `miIO.info` requests time
out. Map retrieval through Xiaomi Cloud works and produces an encrypted map
that can contain the vacuum position and cleaning path.

### Requirements

- Mac and vacuum connected to the same non-guest Wi-Fi network
- vacuum online in Xiaomi Home
- project environment in `venv/` (Python 3.10)
- map parser environment in `.venv-map/` (Python 3.11)
- Xiaomi device metadata in
  `xiaomi-cleaning-trajectory-retrieve-test/.token`

The `.token` file must contain `ID`, `MAC`, `TOKEN`, and `MODEL`. Do not store a
local IP address because DHCP can change it.

### Find the current IP

```bash
cd xiaomi-cleaning-trajectory-retrieve-test
../venv/bin/miiocli discover
```

Confirm basic connectivity with the discovered address:

```bash
ping -c 2 VACUUM_IP
```

Charging does not prevent network communication.

### Download the current map

Start a cleaning run in Xiaomi Home and allow the vacuum to move before taking
a snapshot. Then run:

```bash
cd xiaomi-cleaning-trajectory-retrieve-test
../venv/bin/python download_s40c_map.py \
  --server de \
  --output logs/s40c_map.zlib.enc
```

Open `http://127.0.0.1:31415`, scan the displayed QR code, and approve the
Xiaomi login. The script performs read-only cloud requests and does not start,
pause, or stop cleaning.

Use the Xiaomi server configured in the app if it is not `de`.

### Extract trajectory coordinates

After downloading a map, extract its cleaning path with the Python 3.11 map
environment:

```bash
cd xiaomi-cleaning-trajectory-retrieve-test
../.venv-map/bin/python extract_s40c_trajectory.py
```

This produces:

- `logs/s40c_trajectory.csv`: segment, point index, x, y, and angle
- `logs/s40c_trajectory_metadata.json`: map dimensions, point count, and final
  vacuum position

### Render a trajectory video

```bash
cd xiaomi-cleaning-trajectory-retrieve-test
MPLBACKEND=Agg MPLCONFIGDIR="$PWD/.cache/matplotlib" \
  XDG_CACHE_HOME="$PWD/.cache" \
  ../.venv-map/bin/python visualization/visualize_s40c_trajectory.py \
  --duration 30 --fps 30 --output visualization/s40c_trajectory.mp4
```

The video progressively draws the cleaning trail and shows the current point,
vacuum marker, and heading direction. `ffmpeg` must be installed.

### Verified result

Cloud map download and S40C map decryption were verified. The first test was
taken while the vacuum was docked and contained:

- map dimensions: 164 x 114 cells
- current vacuum position
- zero trajectory points because no cleaning run was active

Take the next map snapshot during or immediately after an active cleaning run
to retrieve cleaning-path points. The compatible parser packages are:

```text
vacuum-map-parser-base==0.1.5
vacuum-map-parser-xiaomi==0.1.3
```

## Security

- Never print, share, or commit `.token`.
- Treat downloaded maps as private household data.
- Keep `.token` permissions restricted (`chmod 600 .token`).
- Generated maps and virtual environments are ignored by Git.
