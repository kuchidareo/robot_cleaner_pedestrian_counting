import csv
import os
import sys
import termios
import threading
import time
import tty
from typing import Optional


class AnnotationWriter:
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.csv_path = os.path.join(out_dir, "annotation.csv")
        self._lock = threading.Lock()
        self._annotations: list[tuple[float, bool]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stdin_fd: Optional[int] = None
        self._old_term = None

        os.makedirs(out_dir, exist_ok=True)
        self._rewrite_csv()

    def _format_log_time(self, timestamp: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(timestamp))

    def _count_text(self) -> str:
        return f"count={len(self._annotations)}"

    def start(self) -> None:
        if not sys.stdin.isatty():
            print("[annotation] stdin is not a TTY; keyboard annotation is disabled.")
            return
        if self._thread is not None:
            return
        self._stdin_fd = sys.stdin.fileno()
        self._old_term = termios.tcgetattr(self._stdin_fd)
        tty.setcbreak(self._stdin_fd)
        self._thread = threading.Thread(target=self._run, name="annotation-listener", daemon=True)
        self._thread.start()
        print("[annotation] Space: add annotation, Backspace: remove last annotation, q: quit listener")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._stdin_fd is not None and self._old_term is not None:
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._old_term)
            self._stdin_fd = None
            self._old_term = None

    def add_annotation(self, timestamp: Optional[float] = None) -> float:
        ts = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            self._annotations.append((ts, True))
            self._rewrite_csv_locked()
        print(f"[annotation] added {self._format_log_time(ts)} {self._count_text()}")
        return ts

    def remove_last_annotation(self) -> Optional[float]:
        with self._lock:
            if not self._annotations:
                print(f"[annotation] nothing to remove {self._count_text()}")
                return None
            ts, _ = self._annotations.pop()
            self._rewrite_csv_locked()
        print(f"[annotation] removed {self._format_log_time(ts)} {self._count_text()}")
        return ts

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ch = sys.stdin.read(1)
            except Exception as exc:
                print(f"[annotation] listener stopped: {exc}")
                return
            if not ch:
                continue
            if ch == " ":
                self.add_annotation()
            elif ch in ("\x08", "\x7f"):
                self.remove_last_annotation()
            elif ch.lower() == "q":
                print("[annotation] listener quit requested")
                self._stop.set()

    def _rewrite_csv(self) -> None:
        with self._lock:
            self._rewrite_csv_locked()

    def _rewrite_csv_locked(self) -> None:
        with open(self.csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "annotation"])
            for ts, annotation in self._annotations:
                writer.writerow([f"{ts:.6f}", annotation])
            f.flush()
            os.fsync(f.fileno())