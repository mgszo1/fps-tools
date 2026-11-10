import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture
def make_video(tmp_path, ffmpeg):
    def make(name="原始 视频.mp4", fps="24", frames=240, audio=True, extra=(), codec="libx264"):
        path = tmp_path / name
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               f"testsrc2=size=160x90:rate={fps}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
        cmd += ["-map", "0:v"]
        if audio:
            cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-t", str(frames / float(__import__('fractions').Fraction(fps)))]
        cmd += ["-frames:v", str(frames), "-c:v", codec]
        if codec == "libx264":
            cmd += ["-bf", "3", "-g", "24"]
        cmd += [*extra, str(path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return path
    return make
