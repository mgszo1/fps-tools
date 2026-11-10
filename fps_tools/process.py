"""Run the bundled engine without a console, with bounded cancellation."""
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable

import imageio_ffmpeg


class MediaError(Exception):
    pass


class Cancelled(MediaError):
    pass


def check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise Cancelled("已取消，原文件未修改。")


def engine_path() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_engine(args: list[str], cancel: threading.Event | None = None,
               progress: Callable[[float], None] | None = None, duration: float = 0):
    check_cancel(cancel)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    event = cancel or threading.Event()
    with tempfile.TemporaryFile(mode="w+b") as log, tempfile.TemporaryFile(mode="w+b") as updates:
        process = subprocess.Popen([engine_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
                                    "-progress", "pipe:1", *args], stdin=subprocess.DEVNULL,
                                   stdout=updates, stderr=log, creationflags=flags)
        try:
            while process.poll() is None:
                if event.wait(.1):
                    raise Cancelled("已取消，临时文件已清理。")
                if progress and duration:
                    updates.seek(0)
                    lines = updates.read().decode("utf-8", "replace").splitlines()
                    times = [x.split("=", 1)[1] for x in lines if x.startswith("out_time_us=")]
                    if times:
                        try:
                            progress(max(0., min(.99, int(times[-1]) / 1e6 / duration)))
                        except ValueError:
                            pass
            check_cancel(cancel)
            if process.returncode:
                log.seek(0)
                details = log.read().decode("utf-8", "replace")[-4000:]
                raise MediaError("此文件无法在保留视频编码和原格式的条件下导出。\n" + details)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
