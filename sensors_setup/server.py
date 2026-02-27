import asyncio
import csv
import os
import struct
import time
from dataclasses import dataclass
from typing import Dict, Tuple, Union
import websockets
import numpy as np



# WebSocket URLs
URLS = {
    "cam2": "ws://192.168.121.:84",
    "cam3": "ws://192.168.121.44:85",
    "cam4": "ws://192.168.121.139:86",
    "main": "ws://192.168.121.161:81"
}

BASE_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
PRINT_EVERY = 10
THERMAL_DECIMALS = 2

# Frame sizes
FRAME_WIDTH = 32
FRAME_HEIGHT = 24

# -----------------------------------------------------------------------------
# Packet structs (unified)
# -----------------------------------------------------------------------------
# Header (no-magic): H cols + H rows  (4 bytes)
HDR = struct.Struct("<HH")

# MainController:
#   int16 motion, int16 presence, int16 pir_value,
#   float ambient, float distance_cm,
#   float gyroX, gyroY, gyroZ,
#   float accelX, accelY, accelZ
META_MAIN = struct.Struct("<hhh" + "f" * 8)

# Fixed MLX size expected on the wire
N_PIXELS = FRAME_WIDTH * FRAME_HEIGHT
BYTES_THERMAL = N_PIXELS * 4

@dataclass
class MainMeta:
    motion: int
    presence: int
    pir_value: int  # 0/1
    ambient: float
    distance_cm: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    accel_x: float
    accel_y: float
    accel_z: float


def _floats_from_bytes(buf: bytes, offset: int, n: int) -> Union["np.ndarray", list]:
    return np.frombuffer(buf, dtype="<f4", count=n, offset=offset)


def parse_packet(sensor_name: str, buf: bytes) -> Tuple[int, int, int, Union[MainMeta, None], Union["np.ndarray", list], Union["np.ndarray", list, None]]:
    """Decode packets from sensors.

    Returns: (version, cols, rows, meta_or_None, frame1, frame2_or_None)  # version is always 0 (no versioned header)

    - MainController sends: header + META_MAIN + 1 thermal frame
    - ThermalCamera3/4 send: header + 1 thermal frame

    We disambiguate by expected total length.
    """
    if len(buf) < HDR.size:
        raise ValueError(f"too short: {len(buf)}")

    cols, rows = HDR.unpack_from(buf, 0)
    version = 0
    off = HDR.size

    n = int(cols) * int(rows)
    if n <= 0:
        raise ValueError(f"bad dims: {cols}x{rows}")
    if n != N_PIXELS:
        raise ValueError(f"unexpected dims: {cols}x{rows} expected {FRAME_WIDTH}x{FRAME_HEIGHT}")

    # Expected sizes
    need_main = off + META_MAIN.size + BYTES_THERMAL
    need_thermal = off + BYTES_THERMAL

    if len(buf) == need_main:
        motion, presence, pir_value, ambient, distance_cm, gx, gy, gz, ax, ay, az = META_MAIN.unpack_from(buf, off)
        meta = MainMeta(
            motion=int(motion),
            presence=int(presence),
            pir_value=int(pir_value),
            ambient=float(ambient),
            distance_cm=float(distance_cm),
            gyro_x=float(gx),
            gyro_y=float(gy),
            gyro_z=float(gz),
            accel_x=float(ax),
            accel_y=float(ay),
            accel_z=float(az),
        )
        off2 = off + META_MAIN.size
        f1 = _floats_from_bytes(buf, off2, n)
        return version, cols, rows, meta, f1, None

    if len(buf) == need_thermal:
        f1 = _floats_from_bytes(buf, off, n)
        return version, cols, rows, None, f1, None

    raise ValueError(
        f"bad packet size for {sensor_name}: got {len(buf)} expected {need_main} (main) or {need_thermal} (thermal)"
    )

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

    # Some sensors may still send thermal frames as CSV text.
    # Buffer 32-float rows until we have a full 32x24 frame.
    text_row_buf: list[float] = []

    def _try_parse_text_thermal(s: str) -> Union["np.ndarray", None]:
        s = s.strip()
        if not s:
            return None
        # Normalize any newlines into commas
        s_norm = s.replace("\n", ",").replace("\r", ",")
        parts = [p for p in s_norm.split(",") if p.strip() != ""]
        try:
            floats = [float(p) for p in parts]
        except Exception:
            return None

        n = FRAME_WIDTH * FRAME_HEIGHT
        # Full frame in one message
        if len(floats) >= n:
            return np.asarray(floats[:n], dtype=np.float32)

        # Row-by-row messages
        if len(floats) == FRAME_WIDTH:
            text_row_buf.extend(floats)
            if len(text_row_buf) >= n:
                frame = np.asarray(text_row_buf[:n], dtype=np.float32)
                del text_row_buf[:n]
                return frame
        return None

    def _flush_all() -> None:
        imu_csv.flush()
        pir_csv.flush()
        distance_csv.flush()
        for sink in thermal_csv.values():
            sink.flush()

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                print(f"Connected: {name} -> {url}")

                while True:
                    msg = await ws.recv()
                    ts = time.time()

                    # TEXT thermal (CSV) fallback
                    if isinstance(msg, str):
                        frame = _try_parse_text_thermal(msg)
                        if frame is None:
                            # Ignore non-thermal text
                            continue
                        # Treat as a single-frame thermal packet (no meta)
                        version, cols, rows, meta, f1, f2 = 0, FRAME_WIDTH, FRAME_HEIGHT, None, frame, None
                    else:
                        try:
                            version, cols, rows, meta, f1, f2 = parse_packet(name, msg)
                        except Exception as e:
                            print(f"[{name}] parse error: {e} (bytes={len(msg)})")
                            continue

                    count += 1
                    fps = rate.tick()

                    # meta -> imu/pir/distance
                    if meta is not None:
                        imu_csv.write([
                            f"{ts:.6f}",
                            f"{meta.gyro_x:.6f}", f"{meta.gyro_y:.6f}", f"{meta.gyro_z:.6f}",
                            f"{meta.accel_x:.6f}", f"{meta.accel_y:.6f}", f"{meta.accel_z:.6f}",
                        ])
                        pir_csv.write([f"{ts:.6f}", meta.motion, meta.presence, meta.pir_value, f"{meta.ambient:.6f}"])
                        distance_csv.write([f"{ts:.6f}", f"{meta.distance_cm:.6f}"])

                    # thermal -> per-sensor files
                    if name == "main":
                        thermal_csv["main"].write(thermal_row(ts, f1))
                    elif name == "cam2":
                        thermal_csv["cam2"].write(thermal_row(ts, f1))
                    elif name == "cam3":
                        thermal_csv["cam3"].write(thermal_row(ts, f1))
                    elif name == "cam4":
                        thermal_csv["cam4"].write(thermal_row(ts, f1))

                    if count % PRINT_EVERY == 0:
                        _flush_all()

                        mn, mx = flat_min_max(f1)
                        if meta is not None:
                            extra = (
                                f" | motion={meta.motion} presence={meta.presence} pir={meta.pir_value}"
                                f" amb={meta.ambient:.2f} dist={meta.distance_cm:.1f}cm"
                                f" gyro=({meta.gyro_x:.2f},{meta.gyro_y:.2f},{meta.gyro_z:.2f})"
                                f" accel=({meta.accel_x:.2f},{meta.accel_y:.2f},{meta.accel_z:.2f})"
                            )
                        else:
                            extra = ""
                        print(f"[{name}] v{version} {cols}x{rows} fps~{fps:.2f} value[min,max]=({mn:.1f},{mx:.1f}){extra}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[{name}] connect/error: {e} -> retry in 1s")
            await asyncio.sleep(1)


async def main():
    # Create a per-run output folder like out/20260228_1234
    run_id = time.strftime("%Y%m%d_%H%M", time.localtime())
    out_dir = os.path.join(BASE_OUT_DIR, run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Output dir: {out_dir}")

    imu_csv = CsvSink(
        os.path.join(out_dir, "imu.csv"),
        ["timestamp", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps", "accel_x_mps2", "accel_y_mps2", "accel_z_mps2"],
    )
    pir_csv = CsvSink(os.path.join(out_dir, "pir.csv"), ["timestamp", "motion", "presence", "pir_value", "ambient"])
    distance_csv = CsvSink(os.path.join(out_dir, "distance.csv"), ["timestamp", "distance_cm"])

    thermal_header = ["timestamp"] + [f"p{i}" for i in range(32 * 24)]
    thermal_csv = {
        "main": CsvSink(os.path.join(out_dir, "thermal_main.csv"), thermal_header),
        "cam2": CsvSink(os.path.join(out_dir, "thermal_cam2.csv"), thermal_header),
        "cam3": CsvSink(os.path.join(out_dir, "thermal_cam3.csv"), thermal_header),
        "cam4": CsvSink(os.path.join(out_dir, "thermal_cam4.csv"), thermal_header),
    }

    tasks = [
        listen_sensor("main", URLS["main"], imu_csv, pir_csv, distance_csv, thermal_csv),
        # listen_sensor("cam2", URLS["cam2"], imu_csv, pir_csv, distance_csv, thermal_csv),
        # listen_sensor("cam3", URLS["cam3"], imu_csv, pir_csv, distance_csv, thermal_csv),
        # listen_sensor("cam4", URLS["cam4"], imu_csv, pir_csv, distance_csv, thermal_csv),
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")