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


@pytest.fixture
def make_rounded_audio(make_video):
    """AAC samples are intact, but MP4 sample durations have one-tick rounding.

    Rebuild only the trailing moov box so media offsets and payloads stay intact.
    Keep mdhd/elst declarations, matching files from editors with rounded stts.
    """
    import itertools
    import struct

    def make(name="rounded.mp4", sample_rate=48000, rounding=-1, declared_extra_ms=0):
        path = make_video(name=name, fps="30", frames=152,
                          extra=("-ar", str(sample_rate)))
        data = path.read_bytes()

        def boxes(blob):
            offset = 0
            while offset < len(blob):
                size, tag = struct.unpack_from(">I4s", blob, offset)
                assert 8 <= size <= len(blob)-offset
                yield tag, blob[offset+8:offset+size]
                offset += size

        def rebuild(blob, audio=False):
            result = bytearray()
            for tag, payload in boxes(blob):
                if tag == b"trak":
                    audio_track = any(t == b"mdia" and any(
                        h == b"hdlr" and p[8:12] == b"soun" for h, p in boxes(v))
                        for t, v in boxes(payload))
                    payload = rebuild(payload, audio_track)
                elif tag in {b"moov", b"mdia", b"minf", b"stbl", b"edts"}:
                    payload = rebuild(payload, audio)
                elif audio and tag == b"elst" and declared_extra_ms:
                    # FFmpeg defaults to a 1 kHz movie clock and v0 edit list.
                    assert payload[0] == 0
                    payload = bytearray(payload)
                    duration = struct.unpack_from(">I", payload, 8)[0]
                    struct.pack_into(">I", payload, 8, duration+declared_extra_ms)
                elif audio and tag == b"stts":
                    count = struct.unpack_from(">I", payload, 4)[0]
                    durations = []
                    for i in range(count):
                        n, duration = struct.unpack_from(">II", payload, 8+8*i)
                        durations.extend([duration]*n)
                    for i in range(32, len(durations)-1, 62):
                        durations[i] += rounding
                    runs = [(len(list(g)), d) for d, g in itertools.groupby(durations)]
                    payload = payload[:4] + struct.pack(">I", len(runs))
                    payload += b"".join(struct.pack(">II", n, d) for n, d in runs)
                result += struct.pack(">I4s", len(payload)+8, tag) + payload
            return bytes(result)

        assert list(boxes(data))[-1][0] == b"moov"
        path.write_bytes(rebuild(data))
        return path
    return make
