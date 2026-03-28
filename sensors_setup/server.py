import asyncio
import csv
import os
import struct
import time
from dataclasses import dataclass
from typing import Dict, Tuple, Union

import numpy as np
import websockets

from annotation import AnnotationWriter

# -----------------------------------------------------------------------------
# Server listen ports (devices connect to this PC)
# -----------------------------------------------------------------------------
SENSOR_PORTS = {
    "thermalcam1": 81,
    "distance": 82,
    "thermalcam2": 84,
    "thermalcam3": 85,
    "thermalcam4": 86,
    "timercam1": 87,
    "timercam2": 88,
    "timercam3": 89,
    "timercam4": 90,
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

# Distance-only sensor sends a single float (distance_cm) as 4 bytes
DIST_ONLY = struct.Struct("<f")

# MainController meta (distance is NOT included; distance comes from dedicated distance device)
# int16 motion, int16 presence
# float ambient,
# float gyroX, gyroY, gyroZ,
# float accelX, accelY, accelZ
# => 2*int16 + 7 floats = 32 bytes
META_MAIN = struct.Struct("<hh" + "f" * 7)

# Fixed MLX size expected on the wire
N_PIXELS = FRAME_WIDTH * FRAME_HEIGHT
BYTES_THERMAL = N_PIXELS * 4

THERMAL_SENSOR_NAMES = {"thermalcam1", "thermalcam2", "thermalcam3", "thermalcam4"}
TIMERCAM_SENSOR_NAMES = {"timercam1", "timercam2", "timercam3", "timercam4"}


@dataclass
class MainMeta:
    motion: int
    presence: int
    ambient: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    accel_x: float
    accel_y: float
    accel_z: float


def _floats_from_bytes(buf: bytes, offset: int, n: int) -> Union[np.ndarray, list]:
    return np.frombuffer(buf, dtype="<f4", count=n, offset=offset)


def parse_packet(
    sensor_name: str, buf: bytes
) -> Tuple[int, int, int, Union[MainMeta, None], Union[np.ndarray, list], Union[np.ndarray, list, None]]:
    """Decode packets from sensors.

    Returns: (version, cols, rows, meta_or_None, frame1, frame2_or_None)
    - thermalcam1 sends: header + META_MAIN(32 bytes) + 1 thermal frame
    - thermalcam2/3/4 send: header + 1 thermal frame
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

    need_main = off + META_MAIN.size + BYTES_THERMAL
    need_thermal = off + BYTES_THERMAL

    if len(buf) == need_main:
        motion, presence, ambient, gx, gy, gz, ax, ay, az = META_MAIN.unpack_from(buf, off)
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


def thermal_row(ts: float, flat: Union[np.ndarray, list]) -> list:
    vals = flat.tolist() if hasattr(flat, "tolist") else flat
    return [f"{ts:.6f}"] + [_fmt(float(v)) for v in vals]


def flat_min_max(flat: Union[np.ndarray, list]) -> Tuple[float, float]:
    if hasattr(flat, "min"):
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


# -----------------------------------------------------------------------------
# Server handlers
# -----------------------------------------------------------------------------

async def sensor_handler(
    websocket,
    *,
    name: str,
    imu_csv: CsvSink,
    pir_csv: CsvSink,
    distance_csv: CsvSink,
    thermal_csv: Dict[str, CsvSink],
    image_csv: Dict[str, CsvSink],
    image_dir: Dict[str, str],
):
    rate = Rate()
    count = 0
    text_row_buf: list[float] = []

    def _try_parse_text_thermal(s: str) -> Union[np.ndarray, None]:
        s = s.strip()
        if not s:
            return None
        s_norm = s.replace("\n", ",").replace("\r", ",")
        parts = [p for p in s_norm.split(",") if p.strip() != ""]
        try:
            floats = [float(p) for p in parts]
        except Exception:
            return None

        n = FRAME_WIDTH * FRAME_HEIGHT
        if len(floats) >= n:
            return np.asarray(floats[:n], dtype=np.float32)

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
        for sink in image_csv.values():
            sink.flush()

    path = ""
    try:
        if hasattr(websocket, "path"):
            path = websocket.path or ""
        elif hasattr(websocket, "request") and websocket.request is not None:
            path = getattr(websocket.request, "path", "") or ""
    except Exception:
        path = ""

    peer = getattr(websocket, "remote_address", None)
    print(f"Connected: {name} from {peer} (path={path})")

    try:
        async for msg in websocket:
            ts = time.time()

            if isinstance(msg, str):
                frame = _try_parse_text_thermal(msg)
                if frame is None:
                    continue
                version, cols, rows, meta, f1, f2 = 0, FRAME_WIDTH, FRAME_HEIGHT, None, frame, None
            else:
                if name in TIMERCAM_SENSOR_NAMES:
                    filename = f"{name}_{int(ts * 1000000)}.jpg"
                    file_path = os.path.join(image_dir[name], filename)
                    with open(file_path, "wb") as fh:
                        fh.write(msg)
                    image_csv[name].write([f"{ts:.6f}", filename, str(len(msg))])

                    count += 1
                    fps = rate.tick()
                    if count % PRINT_EVERY == 0:
                        _flush_all()
                        print(f"[{name}] fps~{fps:.2f} jpeg_bytes={len(msg)} saved={filename}")
                    continue

                if name == "distance" and len(msg) == DIST_ONLY.size:
                    (dcm,) = DIST_ONLY.unpack(msg)
                    distance_csv.write([f"{ts:.6f}", f"{float(dcm):.6f}"])

                    count += 1
                    fps = rate.tick()
                    if count % PRINT_EVERY == 0:
                        _flush_all()
                        print(f"[{name}] fps~{fps:.2f} distance_cm={float(dcm):.2f}")
                    continue

                try:
                    version, cols, rows, meta, f1, f2 = parse_packet(name, msg)
                except Exception as e:
                    print(f"[{name}] parse error: {e} (bytes={len(msg)})")
                    continue

            count += 1
            fps = rate.tick()

            if meta is not None:
                imu_csv.write([
                    f"{ts:.6f}",
                    f"{meta.gyro_x:.6f}", f"{meta.gyro_y:.6f}", f"{meta.gyro_z:.6f}",
                    f"{meta.accel_x:.6f}", f"{meta.accel_y:.6f}", f"{meta.accel_z:.6f}",
                ])
                pir_csv.write([f"{ts:.6f}", meta.motion, meta.presence, f"{meta.ambient:.6f}"])

            if name in THERMAL_SENSOR_NAMES:
                thermal_csv[name].write(thermal_row(ts, f1))

            if count % PRINT_EVERY == 0:
                _flush_all()
                mn, mx = flat_min_max(f1)
                if meta is not None:
                    extra = (
                        f" | motion={meta.motion} presence={meta.presence}"
                        f" amb={meta.ambient:.2f}"
                        f" gyro=({meta.gyro_x:.2f},{meta.gyro_y:.2f},{meta.gyro_z:.2f})"
                        f" accel=({meta.accel_x:.2f},{meta.accel_y:.2f},{meta.accel_z:.2f})"
                    )
                else:
                    extra = ""
                print(f"[{name}] v{version} {cols}x{rows} fps~{fps:.2f} value[min,max]=({mn:.1f},{mx:.1f}){extra}")

    except websockets.ConnectionClosed as e:
        code = getattr(e, "code", None)
        reason = getattr(e, "reason", "")
        print(f"Disconnected: {name} from {peer} (code={code} reason={reason})")
    except Exception as e:
        import traceback
        print(f"[{name}] handler error: {e}")
        traceback.print_exc()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

async def main():
    run_id = time.strftime("%Y%m%d_%H%M", time.localtime())
    out_dir = os.path.join(BASE_OUT_DIR, run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Output dir: {out_dir}")

    annotation_writer = AnnotationWriter(out_dir)
    annotation_writer.start()

    imu_csv = CsvSink(
        os.path.join(out_dir, "imu.csv"),
        ["timestamp", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps", "accel_x_mps2", "accel_y_mps2", "accel_z_mps2"],
    )
    pir_csv = CsvSink(os.path.join(out_dir, "pir.csv"), ["timestamp", "motion", "presence", "ambient"])
    distance_csv = CsvSink(os.path.join(out_dir, "distance.csv"), ["timestamp", "distance_cm"])

    thermal_header = ["timestamp"] + [f"p{i}" for i in range(FRAME_WIDTH * FRAME_HEIGHT)]
    thermal_csv = {
        name: CsvSink(os.path.join(out_dir, f"{name}.csv"), thermal_header)
        for name in sorted(THERMAL_SENSOR_NAMES)
    }

    image_csv = {}
    image_dir = {}
    for name in sorted(TIMERCAM_SENSOR_NAMES):
        image_dir[name] = os.path.join(out_dir, name)
        os.makedirs(image_dir[name], exist_ok=True)
        image_csv[name] = CsvSink(os.path.join(out_dir, f"{name}.csv"), ["timestamp", "filename", "bytes"])

    servers = []

    for sensor_name, port in SENSOR_PORTS.items():
        async def _make_handler(ws, *, _name=sensor_name):
            return await sensor_handler(
                ws,
                name=_name,
                imu_csv=imu_csv,
                pir_csv=pir_csv,
                distance_csv=distance_csv,
                thermal_csv=thermal_csv,
                image_csv=image_csv,
                image_dir=image_dir,
            )

        server = await websockets.serve(_make_handler, host="0.0.0.0", port=port, ping_interval=None)
        servers.append(server)
        print(f"Listening: {sensor_name} on ws://0.0.0.0:{port}/")

    try:
        await asyncio.Future()
    finally:
        annotation_writer.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
