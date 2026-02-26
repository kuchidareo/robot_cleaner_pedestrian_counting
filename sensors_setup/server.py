import asyncio
import csv
import os
import struct
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union
import websockets
import numpy as np



# WebSocket URLs
URLS = {
    "cam3": "ws://192.168.121.44:85",
    "cam4": "ws://192.168.121.139:86",
    "main": "ws://192.168.121.161:81"
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
PRINT_EVERY = 10
THERMAL_DECIMALS = 2

# Frame sizes
FRAME_WIDTH = 32
FRAME_HEIGHT = 24

# -----------------------------------------------------------------------------
# MC packet structs
# -----------------------------------------------------------------------------
# Two header variants:
#  - Old (magic-based): 2s magic + B version + B reserved + H cols + H rows
#  - New (no-magic):    B version + B reserved + H cols + H rows
HDR_MAGIC = struct.Struct("<2sBBHH")
HDR_NOMAG = struct.Struct("<BBHH")

# Meta variants
# MainController v1 (OLD): motion, presence, ambient, gyroMag, accelMag
META_MAIN_V1_OLD = struct.Struct("<hhfff")
# MainController v1 (NEW): motion, presence, ambient, gyroX, gyroY, gyroZ, accelX, accelY, accelZ
META_MAIN_V1_NEW = struct.Struct("<hh" + "f" * 7)

# Global dictionary for images
latest_images = {
    "cam3": None,
    "cam4": None,
    "main_front": None,
    "main_rear": None
}

@dataclass
class MainMeta:
    motion: int
    presence: int
    ambient: float
    # NEW IMU fields (deg/s and m/s^2)
    gyro_x: float
    gyro_y: float
    gyro_z: float
    accel_x: float
    accel_y: float
    accel_z: float

    # OLD fields for backward compatibility (may be None)
    gyro_mag: Optional[float] = None
    accel_mag: Optional[float] = None

    # Distance (will be added later on-device)
    distance_cm: Optional[float] = None

def _floats_from_bytes(buf: bytes, offset: int, n: int) -> Union["np.ndarray", list]:
    return np.frombuffer(buf, dtype="<f4", count=n, offset=offset)

def parse_mc_packet(buf: bytes) -> Tuple[int, int, int, Optional[MainMeta], Union["np.ndarray", list], Optional[Union["np.ndarray", list]]]:
    if len(buf) < HDR_NOMAG.size:
        raise ValueError(f"too short: {len(buf)}")

    # Detect header variant
    off = 0
    if len(buf) >= HDR_MAGIC.size and buf[:2] == b"MC":
        magic, version, _rsv, cols, rows = HDR_MAGIC.unpack_from(buf, 0)
        off = HDR_MAGIC.size
    else:
        version, _rsv, cols, rows = HDR_NOMAG.unpack_from(buf, 0)
        off = HDR_NOMAG.size

    n = int(cols) * int(rows)
    if n <= 0:
        raise ValueError(f"bad dims: {cols}x{rows}")

    # MainController packets
    if version == 1:
        # Decide which v1 meta we have (old vs new) by total length.
        need_old = off + META_MAIN_V1_OLD.size + (n * 4 * 2)
        need_new = off + META_MAIN_V1_NEW.size + (n * 4 * 2)

        meta: Optional[MainMeta] = None

        if len(buf) == need_new:
            motion, presence, ambient, gx, gy, gz, ax, ay, az = META_MAIN_V1_NEW.unpack_from(buf, off)
            meta = MainMeta(
                motion=int(motion),
                presence=int(presence),
                ambient=float(ambient),
                gyro_x=float(gx),
                gyro_y=float(gy),
                gyro_z=float(gz),
                accel_x=float(ax),
                accel_y=float(ay),
                accel_z=float(az),
                gyro_mag=None,
                accel_mag=None,
            )
            off2 = off + META_MAIN_V1_NEW.size
        elif len(buf) == need_old:
            motion, presence, ambient, gyro_mag, accel_mag = META_MAIN_V1_OLD.unpack_from(buf, off)
            meta = MainMeta(
                motion=int(motion),
                presence=int(presence),
                ambient=float(ambient),
                gyro_x=float("nan"),
                gyro_y=float("nan"),
                gyro_z=float("nan"),
                accel_x=float("nan"),
                accel_y=float("nan"),
                accel_z=float("nan"),
                gyro_mag=float(gyro_mag),
                accel_mag=float(accel_mag),
            )
            off2 = off + META_MAIN_V1_OLD.size
        else:
            # Helpful error to debug mismatched firmware/server
            raise ValueError(f"bad v1 size: got {len(buf)} expected {need_new} (new) or {need_old} (old)")

        f1 = _floats_from_bytes(buf, off2, n)
        off2 += n * 4
        f2 = _floats_from_bytes(buf, off2, n)
        return version, cols, rows, meta, f1, f2

    # Camera packets (single thermal) - keep behavior
    if version == 2:
        need = off + (n * 4)
        if len(buf) != need:
            raise ValueError(f"bad v2 size: got {len(buf)} expected {need}")
        f1 = _floats_from_bytes(buf, off, n)
        return version, cols, rows, None, f1, None

    raise ValueError(f"unsupported version: {version}")

# -----------------------------------------------------------------------------
# CSV outputs
# -----------------------------------------------------------------------------

class CsvSink:
    def __init__(self, path: str, header: list):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, "a", newline="")
        self._w = csv.writer(self._fh)
        if os.stat(path).st_size == 0:
            self._w.writerow(header)
            self._fh.flush()

    def write(self, row: list):
        self._w.writerow(row)

    def flush(self):
        self._fh.flush()


def _fmt(x: float) -> str:
    return f"{x:.{THERMAL_DECIMALS}f}"


def thermal_row(ts: float, flat: Union["np.ndarray", list]) -> list:
    if np is not None and hasattr(flat, "tolist"):
        vals = flat.tolist()
    else:
        vals = flat
    return [f"{ts:.6f}"] + [_fmt(float(v)) for v in vals]


def flat_min_max(flat: Union["np.ndarray", list]) -> Tuple[float, float]:
    if np is not None and hasattr(flat, "min"):
        return float(np.nanmin(flat)), float(np.nanmax(flat))
    mn = float("inf")
    mx = float("-inf")
    for v in flat:
        fv = float(v)
        if fv < mn:
            mn = fv
        if fv > mx:
            mx = fv
    return mn, mx


@dataclass
class Rate:
    t0: float = 0.0
    n: int = 0

    def tick(self) -> float:
        now = time.time()
        if self.n == 0:
            self.t0 = now
            self.n = 1
            return 0.0
        self.n += 1
        dt = now - self.t0
        return (self.n - 1) / dt if dt > 0 else 0.0

async def listen_sensor(
    name: str,
    url: str,
    imu_csv: CsvSink,
    pir_csv: CsvSink,
    distance_csv: CsvSink,
    thermal_csv: Dict[str, CsvSink],
):
    rate = Rate()
    count = 0
    # Some sensors may send thermal frames as CSV text (comma-separated floats).
    # Buffer 32-float rows until we have a full 32x24 frame.
    text_row_buf: list[float] = []

    def _thermal_key(sensor_name: str) -> Optional[str]:
        return {"cam3": "cam3", "cam4": "cam4", "main": "main1"}.get(sensor_name)

    def _write_thermal(sensor_name: str, ts: float, flat) -> None:
        key = _thermal_key(sensor_name)
        if key is None:
            return
        thermal_csv[key].write(thermal_row(ts, flat))

    def _flush_all() -> None:
        imu_csv.flush()
        pir_csv.flush()
        distance_csv.flush()
        for sink in thermal_csv.values():
            sink.flush()

    def _log_text_frame(sensor_name: str, fps: float, flat) -> None:
        mn, mx = flat_min_max(flat)
        print(f"[{sensor_name}] TEXT frame {FRAME_WIDTH}x{FRAME_HEIGHT} fps~{fps:.1f} f1[min,max]=({mn:.1f},{mx:.1f})")

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                print(f"Connected: {name} -> {url}")

                while True:
                    msg = await ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        head = msg[:16]
                        print(f"[{name}] received binary: bytes={len(msg)} head={head!r}")
                    else:
                        print(f"[{name}] received text: {msg[:120]!r}")
                    ts = time.time()

                    if isinstance(msg, str):
                        # cam3 may send CSV text: either a full 32x24 frame (768 floats)
                        # or a single row (32 floats) per message.
                        s = msg.strip()
                        s_norm = s.replace("\n", ",").replace("\r", ",")
                        parts = [p for p in s_norm.split(",") if p.strip() != ""]

                        try:
                            floats = [float(p) for p in parts]
                        except Exception:
                            # Not parseable as float CSV; ignore.
                            continue

                        n = FRAME_WIDTH * FRAME_HEIGHT

                        # If a full frame arrives in one message, write it.
                        if len(floats) >= n:
                            frame = floats[:n]
                            _write_thermal(name, ts, frame)
                            count += 1
                            fps = rate.tick()
                            if count % PRINT_EVERY == 0:
                                _flush_all()
                                _log_text_frame(name, fps, frame)
                            continue

                        # If we receive row-by-row (32 floats), buffer until we have 768.
                        if len(floats) == FRAME_WIDTH:
                            text_row_buf.extend(floats)
                            if len(text_row_buf) >= n:
                                frame = text_row_buf[:n]
                                text_row_buf = text_row_buf[n:]
                                _write_thermal(name, ts, frame)
                                count += 1
                                fps = rate.tick()
                                if count % PRINT_EVERY == 0:
                                    _flush_all()
                                    _log_text_frame(name, fps, frame)
                            continue

                        # Unexpected length; ignore.
                        continue

                    try:
                        version, cols, rows, meta, f1, f2 = parse_mc_packet(msg)
                    except Exception as e:
                        print(f"[{name}] parse error: {e} (bytes={len(msg)})")
                        continue

                    count += 1
                    fps = rate.tick()

                    # meta -> imu/pir/distance
                    if meta is not None:
                        # IMU (new) if present; otherwise leave blank fields
                        if meta.gyro_mag is None:
                            imu_csv.write([
                                f"{ts:.6f}",
                                f"{meta.gyro_x:.6f}", f"{meta.gyro_y:.6f}", f"{meta.gyro_z:.6f}",
                                f"{meta.accel_x:.6f}", f"{meta.accel_y:.6f}", f"{meta.accel_z:.6f}",
                            ])
                        else:
                            # Old firmware sent only magnitudes; keep row but blanks for xyz
                            imu_csv.write([f"{ts:.6f}", "", "", "", "", "", ""]) 

                        pir_csv.write([f"{ts:.6f}", meta.motion, meta.presence, f"{meta.ambient:.6f}"])
                        distance_csv.write([f"{ts:.6f}", "" if meta.distance_cm is None else f"{meta.distance_cm:.6f}"])

                    # thermal -> per-sensor files
                    if name == "main":
                        thermal_csv["main1"].write(thermal_row(ts, f1))
                        if f2 is not None:
                            thermal_csv["main2"].write(thermal_row(ts, f2))
                    elif name == "cam3":
                        thermal_csv["cam3"].write(thermal_row(ts, f1))
                    elif name == "cam4":
                        thermal_csv["cam4"].write(thermal_row(ts, f1))

                    if count % PRINT_EVERY == 0:
                        _flush_all()

                        mn, mx = flat_min_max(f1)
                        if meta is not None:
                            if meta.gyro_mag is None:
                                extra = (
                                    f" | motion={meta.motion} presence={meta.presence} amb={meta.ambient:.2f}"
                                    f" gyro=({meta.gyro_x:.2f},{meta.gyro_y:.2f},{meta.gyro_z:.2f})"
                                    f" accel=({meta.accel_x:.2f},{meta.accel_y:.2f},{meta.accel_z:.2f})"
                                )
                            else:
                                extra = (
                                    f" | motion={meta.motion} presence={meta.presence} amb={meta.ambient:.2f}"
                                    f" gyroMag={meta.gyro_mag:.3f} accelMag={meta.accel_mag:.3f}"
                                )
                        else:
                            extra = ""
                        print(f"[{name}] v{version} {cols}x{rows} fps~{fps:.1f} f1[min,max]=({mn:.1f},{mx:.1f}){extra}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[{name}] connect/error: {e} -> retry in 1s")
            await asyncio.sleep(1)


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    imu_csv = CsvSink(
        os.path.join(OUT_DIR, "imu.csv"),
        ["timestamp", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps", "accel_x_mps2", "accel_y_mps2", "accel_z_mps2"],
    )
    pir_csv = CsvSink(os.path.join(OUT_DIR, "pir.csv"), ["timestamp", "motion", "presence", "ambient"])
    distance_csv = CsvSink(os.path.join(OUT_DIR, "distance.csv"), ["timestamp", "distance_cm"])

    thermal_header = ["timestamp"] + [f"p{i}" for i in range(32 * 24)]
    thermal_csv = {
        "main1": CsvSink(os.path.join(OUT_DIR, "thermal_main1.csv"), thermal_header),
        "main2": CsvSink(os.path.join(OUT_DIR, "thermal_main2.csv"), thermal_header),
        "cam3": CsvSink(os.path.join(OUT_DIR, "thermal_cam3.csv"), thermal_header),
        "cam4": CsvSink(os.path.join(OUT_DIR, "thermal_cam4.csv"), thermal_header),
    }

    tasks = [
        # listen_sensor("main", URLS["main"], imu_csv, pir_csv, distance_csv, thermal_csv),
        # listen_sensor("cam3", URLS["cam3"], imu_csv, pir_csv, distance_csv, thermal_csv),
        listen_sensor("cam4", URLS["cam4"], imu_csv, pir_csv, distance_csv, thermal_csv),
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")