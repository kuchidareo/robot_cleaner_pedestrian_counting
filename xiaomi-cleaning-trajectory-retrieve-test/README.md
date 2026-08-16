# Xiaomi S40C trajectory

Run the commands from this directory.

## Setup

```bash
source ../venv/bin/activate
pip install -r requirements.txt
```

## 0. Get `.token`

```bash
python 0_token_extractor.py -s de
```

Choose `q`, scan the QR code with Mi Home, and find
`xiaomi.vacuum.e101gb`.

Create `.token` with the information shown for that device:

```text
NAME: <vacuum name>
ID: <device ID>
TOKEN: <device token>
MODEL: xiaomi.vacuum.e101gb
```

Do not upload `.token` to GitHub.

## 1. Download the trajectory data

```bash
python 1_download_s40c_map.py
```

The files are saved in a timestamped folder:

```text
logs/YYYYMMDDHHMMSS/
```

## 2. Extract the trajectory data

Use the timestamp printed by the previous command:

```bash
python 2_extract_s40c_trajectory.py logs/YYYYMMDDHHMMSS/s40c_map.zlib.enc
```

The CSV is saved here:

```text
logs/YYYYMMDDHHMMSS/s40c_trajectory.csv
```

## 3. Make the trajectory video

```bash
python 3_visualize_s40c_trajectory.py logs/YYYYMMDDHHMMSS/s40c_trajectory.csv
```

The video is saved here:

```text
logs/YYYYMMDDHHMMSS/s40c_trajectory.mp4
```
