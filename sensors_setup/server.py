import asyncio
import csv
import os
import struct
import time
from dataclasses import dataclass
from typing import Dict
import socket

import numpy as np
import websockets

from annotation import AnnotationWriter


RECONNECT_DELAY_SECONDS = 2.0
BASE_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
FRAME_WIDTH = 32
FRAME_HEIGHT = 24
N_PIXELS = FRAME_WIDTH * FRAME_HEIGHT
THERMAL_DECIMALS = 2
LOG_INTERVAL_SECONDS = 10.0

PORTS = {
    "main": 81,
    "distance": 82,
    "thermal2": 84,
    "thermal3": 85,
    "thermal4": 86,
    "timercam1": 87,
    "timercam2": 88,
    "timercam3": 89,
    "timercam4": 90,
}

DISCOVERY_TIMEOUT_SECONDS = 0.25
DISCOVERY_CONCURRENCY = 64

THERMAL_NAMES = {"main", "thermal2", "thermal3", "thermal4"}
THERMAL_ONLY_NAMES = {"thermal2", "thermal3", "thermal4"}
TIMERCAM_NAMES = {"timercam1", "timercam2", "timercam3", "timercam4"}

def websocket_url(name: str, host: str) -> str:
    port = PORTS[name]
    return f"ws://{host}:{port}/"


def local_ipv4_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def local_subnet_prefix() -> str:
    ip = local_ipv4_address()
    parts = ip.split(".")
    if len(parts) != 4:
        raise RuntimeError(f"unexpected local IPv4 address: {ip}")
    return ".".join(parts[:3])


async def tcp_port_open(host: str, port: int, timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> bool:
    try:
        connect_coro = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def discover_host_for_port(name: str, port: int, subnet_prefix: str) -> str | None:
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)
    found_host: str | None = None

    async def probe(host: str) -> str | None:
        nonlocal found_host
        async with semaphore:
            if found_host is not None:
                return None
            if await tcp_port_open(host, port):
                found_host = host
                return host
            return None

    tasks = [asyncio.create_task(probe(f"{subnet_prefix}.{i}")) for i in range(1, 255)]
    try:
        for task in asyncio.as_completed(tasks):
            result = await task
            if result is not None:
                return result
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    print(f"Skipping undiscovered device: {name} (port {port})")
    return None


async def discover_device_hosts() -> Dict[str, str]:
    subnet_prefix = local_subnet_prefix()
    print(f"Discovering devices on {subnet_prefix}.0/24")

    hosts: Dict[str, str] = {}
    for name, port in PORTS.items():
        host = await discover_host_for_port(name, port, subnet_prefix)
        if host is None:
            continue
        hosts[name] = host
        print(f"Discovered: {name} -> {host}:{port}")

    return hosts

HDR = struct.Struct("<HH")
DISTANCE_PACKET = struct.Struct("<f")
MAIN_META = struct.Struct("<hh" + "f" * 7)

BYTES_THERMAL = N_PIXELS * 4
BYTES_MAIN_PACKET = HDR.size + MAIN_META.size + BYTES_THERMAL
BYTES_THERMAL_PACKET = HDR.size + BYTES_THERMAL


@dataclass
class MainPacket:
    motion: int
    presence: int
    ambient: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    accel_x: float
    accel_y: float
    accel_z: float
    thermal: np.ndarray


class CsvSink:
    def __init__(self, path: str, header: list[str]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._fh = open(path, "a", newline="")
        self._writer = csv.writer(self._fh)
        if os.stat(path).st_size == 0:
            self._writer.writerow(header)
            self._fh.flush()

    def write(self, row: list) -> None:
        self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()


def now_ts() -> float:
    return time.time()


def fmt_thermal(v: float) -> str:
    return f"{float(v):.{THERMAL_DECIMALS}f}"


def thermal_csv_row(ts: float, frame: np.ndarray) -> list[str]:
    return [f"{ts:.6f}"] + [fmt_thermal(v) for v in frame.tolist()]


def decode_main_packet(payload: bytes) -> MainPacket:
    if len(payload) != BYTES_MAIN_PACKET:
        raise ValueError(f"main packet size mismatch: got {len(payload)}, expected {BYTES_MAIN_PACKET}")

    cols, rows = HDR.unpack_from(payload, 0)
    if (cols, rows) != (FRAME_WIDTH, FRAME_HEIGHT):
        raise ValueError(f"main frame size mismatch: got {cols}x{rows}, expected {FRAME_WIDTH}x{FRAME_HEIGHT}")

    off = HDR.size
    motion, presence, ambient, gx, gy, gz, ax, ay, az = MAIN_META.unpack_from(payload, off)
    off += MAIN_META.size
    thermal = np.frombuffer(payload, dtype="<f4", count=N_PIXELS, offset=off).copy()

    return MainPacket(
        motion=int(motion),
        presence=int(presence),
        ambient=float(ambient),
        gyro_x=float(gx),
        gyro_y=float(gy),
        gyro_z=float(gz),
        accel_x=float(ax),
        accel_y=float(ay),
        accel_z=float(az),
        thermal=thermal,
    )


def decode_thermal_packet(payload: bytes) -> np.ndarray:
    if len(payload) != BYTES_THERMAL_PACKET:
        raise ValueError(f"thermal packet size mismatch: got {len(payload)}, expected {BYTES_THERMAL_PACKET}")

    cols, rows = HDR.unpack_from(payload, 0)
    if (cols, rows) != (FRAME_WIDTH, FRAME_HEIGHT):
        raise ValueError(f"thermal frame size mismatch: got {cols}x{rows}, expected {FRAME_WIDTH}x{FRAME_HEIGHT}")

    return np.frombuffer(payload, dtype="<f4", count=N_PIXELS, offset=HDR.size).copy()


def frame_min_max(frame: np.ndarray) -> tuple[float, float]:
    return float(np.nanmin(frame)), float(np.nanmax(frame))


def maybe_log_status(
    *,
    name: str,
    total_count: int,
    window_count: int,
    window_started_at: float,
    last_message: str,
) -> tuple[int, float]:
    now = time.monotonic()
    elapsed = now - window_started_at
    if elapsed < LOG_INTERVAL_SECONDS:
        return window_count, window_started_at

    fps = window_count / elapsed if elapsed > 0 else 0.0
    print(f"[{name}] fps={fps:.2f} total={total_count} {last_message}")
    return 0, now


async def handle_main(websocket, sinks: Dict[str, CsvSink]) -> None:
    count = 0
    window_count = 0
    window_started_at = time.monotonic()
    peer = getattr(websocket, "remote_address", None)
    print(f"[main] connected from {peer}")
    print(f"[main] expecting {BYTES_MAIN_PACKET} bytes")

    async for payload in websocket:
        if isinstance(payload, str):
            print("[main] ignoring text payload")
            continue

        ts = now_ts()
        try:
            pkt = decode_main_packet(payload)
        except Exception as exc:
            print(f"[main] decode error: {exc}")
            continue

        sinks["main"].write(thermal_csv_row(ts, pkt.thermal))
        sinks["main_imu"].write([
            f"{ts:.6f}",
            f"{pkt.gyro_x:.6f}",
            f"{pkt.gyro_y:.6f}",
            f"{pkt.gyro_z:.6f}",
            f"{pkt.accel_x:.6f}",
            f"{pkt.accel_y:.6f}",
            f"{pkt.accel_z:.6f}",
        ])
        sinks["main_pir"].write([
            f"{ts:.6f}",
            pkt.motion,
            pkt.presence,
            f"{pkt.ambient:.6f}",
        ])

        count += 1
        window_count += 1
        mn, mx = frame_min_max(pkt.thermal)
        window_count, window_started_at = maybe_log_status(
            name="main",
            total_count=count,
            window_count=window_count,
            window_started_at=window_started_at,
            last_message=(
                f"bytes={len(payload)} thermal[min,max]=({mn:.1f},{mx:.1f}) "
                f"motion={pkt.motion} presence={pkt.presence} ambient={pkt.ambient:.2f} "
                f"gyro=({pkt.gyro_x:.2f},{pkt.gyro_y:.2f},{pkt.gyro_z:.2f})"
            ),
        )


async def handle_distance(websocket, sink: CsvSink) -> None:
    count = 0
    window_count = 0
    window_started_at = time.monotonic()
    peer = getattr(websocket, "remote_address", None)
    print(f"[distance] connected from {peer}")

    async for payload in websocket:
        if isinstance(payload, str):
            print("[distance] ignoring text payload")
            continue
        if len(payload) != DISTANCE_PACKET.size:
            print(f"[distance] bad packet size: {len(payload)}")
            continue

        ts = now_ts()
        (distance_cm,) = DISTANCE_PACKET.unpack(payload)
        sink.write([f"{ts:.6f}", f"{float(distance_cm):.6f}"])

        count += 1
        window_count += 1
        window_count, window_started_at = maybe_log_status(
            name="distance",
            total_count=count,
            window_count=window_count,
            window_started_at=window_started_at,
            last_message=f"distance_cm={float(distance_cm):.2f}",
        )


async def handle_thermal(websocket, name: str, sink: CsvSink) -> None:
    count = 0
    window_count = 0
    window_started_at = time.monotonic()
    peer = getattr(websocket, "remote_address", None)
    print(f"[{name}] connected from {peer}")
    print(f"[{name}] expecting {BYTES_THERMAL_PACKET} bytes")

    async for payload in websocket:
        if isinstance(payload, str):
            print(f"[{name}] ignoring text payload")
            continue

        ts = now_ts()
        try:
            frame = decode_thermal_packet(payload)
        except Exception as exc:
            print(f"[{name}] decode error: {exc}")
            continue

        sink.write(thermal_csv_row(ts, frame))

        count += 1
        window_count += 1
        mn, mx = frame_min_max(frame)
        window_count, window_started_at = maybe_log_status(
            name=name,
            total_count=count,
            window_count=window_count,
            window_started_at=window_started_at,
            last_message=f"bytes={len(payload)} thermal[min,max]=({mn:.1f},{mx:.1f})",
        )


async def handle_timercam(websocket, name: str, csv_sink: CsvSink, image_dir: str) -> None:
    count = 0
    window_count = 0
    window_started_at = time.monotonic()
    peer = getattr(websocket, "remote_address", None)
    print(f"[{name}] connected from {peer}")

    async for payload in websocket:
        if isinstance(payload, str):
            print(f"[{name}] ignoring text payload")
            continue

        ts = now_ts()
        filename = f"{name}_{int(ts * 1000000)}.jpg"
        image_path = os.path.join(image_dir, filename)
        with open(image_path, "wb") as fh:
            fh.write(payload)

        csv_sink.write([f"{ts:.6f}", filename, str(len(payload))])

        count += 1
        window_count += 1
        window_count, window_started_at = maybe_log_status(
            name=name,
            total_count=count,
            window_count=window_count,
            window_started_at=window_started_at,
            last_message=f"jpeg_bytes={len(payload)} file={filename}",
        )


def make_csv_sinks(out_dir: str) -> Dict[str, CsvSink]:
    thermal_header = ["timestamp"] + [f"p{i}" for i in range(N_PIXELS)]
    sinks = {
        "main": CsvSink(os.path.join(out_dir, "main.csv"), thermal_header),
        "main_imu": CsvSink(
            os.path.join(out_dir, "main_imu.csv"),
            ["timestamp", "gyro_x_dps", "gyro_y_dps", "gyro_z_dps", "accel_x_mps2", "accel_y_mps2", "accel_z_mps2"],
        ),
        "main_pir": CsvSink(
            os.path.join(out_dir, "main_pir.csv"),
            ["timestamp", "motion", "presence", "ambient"],
        ),
        "distance": CsvSink(os.path.join(out_dir, "distance.csv"), ["timestamp", "distance_cm"]),
        "thermal2": CsvSink(os.path.join(out_dir, "thermal2.csv"), thermal_header),
        "thermal3": CsvSink(os.path.join(out_dir, "thermal3.csv"), thermal_header),
        "thermal4": CsvSink(os.path.join(out_dir, "thermal4.csv"), thermal_header),
    }

    for name in TIMERCAM_NAMES:
        sinks[name] = CsvSink(os.path.join(out_dir, f"{name}.csv"), ["timestamp", "filename", "bytes"])

    return sinks


async def dispatch(websocket, *, name: str, sinks: Dict[str, CsvSink], out_dir: str) -> None:
    try:
        if name == "main":
            await handle_main(websocket, sinks)
            return
        if name == "distance":
            await handle_distance(websocket, sinks["distance"])
            return
        if name in THERMAL_ONLY_NAMES:
            await handle_thermal(websocket, name, sinks[name])
            return
        if name in TIMERCAM_NAMES:
            image_dir = os.path.join(out_dir, name)
            os.makedirs(image_dir, exist_ok=True)
            await handle_timercam(websocket, name, sinks[name], image_dir)
            return
        print(f"[{name}] no handler")
    except websockets.ConnectionClosed as exc:
        print(f"[{name}] disconnected code={getattr(exc, 'code', None)} reason={getattr(exc, 'reason', '')}")
    except Exception as exc:
        print(f"[{name}] handler error: {exc}")


async def main() -> None:
    run_id = time.strftime("%Y%m%d_%H%M", time.localtime())
    out_dir = os.path.join(BASE_OUT_DIR, run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Output dir: {out_dir}")

    annotation_writer = AnnotationWriter(out_dir)
    annotation_writer.start()

    sinks = make_csv_sinks(out_dir)
    device_hosts = await discover_device_hosts()
    if not device_hosts:
        raise RuntimeError("No devices discovered on the current subnet")

    async def run_device(name: str) -> None:
        while True:
            host = device_hosts[name]
            url = websocket_url(name, host)
            try:
                print(f"Connecting: {name} -> {url}")
                async with websockets.connect(url, ping_interval=None, max_size=None) as websocket:
                    print(f"Connected: {name} -> {url}")
                    await dispatch(websocket, name=name, sinks=sinks, out_dir=out_dir)
            except Exception as exc:
                print(f"[{name}] connection error: {exc}")

            print(f"[{name}] reconnecting in {RECONNECT_DELAY_SECONDS:.1f}s")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    tasks = [asyncio.create_task(run_device(name)) for name in device_hosts]

    try:
        await asyncio.gather(*tasks)
    finally:
        annotation_writer.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for sink in sinks.values():
            sink.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
