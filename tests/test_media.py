import hashlib
import subprocess
import threading
from fractions import Fraction

import av
import numpy as np
import pytest

from fps_tools.media import Cancelled, MediaError, convert, inspect_media, parse_fps


@pytest.mark.parametrize("text,expected", [("30", Fraction(30)), ("29.97", Fraction(30000,1001)),
    ("23.976", Fraction(24000,1001)), ("59.94", Fraction(60000,1001)), ("30000/1001", Fraction(30000,1001)),
    ("12.5", Fraction(25,2))])
def test_rates_are_exact(text, expected):
    assert parse_fps(text) == expected


@pytest.mark.parametrize("text", ["0", "-5", "nan", "inf", "1/0", "241", "", "30; rm", "0.5"])
def test_invalid_rates_rejected(text):
    with pytest.raises(MediaError):
        parse_fps(text)


def packet_hash(path):
    digest = hashlib.sha256()
    with av.open(str(path)) as c:
        for p in c.demux(video=0):
            if p.size:
                digest.update(p.size.to_bytes(8, "big"))
                digest.update(bytes(p))
    return digest.hexdigest()


@pytest.mark.parametrize("target,duration", [("30",8), ("12",20), ("30000/1001",8.008)])
def test_all_240_frames_survive_with_correct_timing(make_video, tmp_path, target, duration):
    src = make_video()
    original = src.read_bytes()
    result = convert(src, parse_fps(target), tmp_path)
    info = inspect_media(result.path)
    assert info.frame_count == 240
    assert float(info.duration) == pytest.approx(duration, abs=.002)
    assert info.fps == parse_fps(target)
    assert packet_hash(src) == packet_hash(result.path)
    assert src.read_bytes() == original
    assert result.path.suffix == src.suffix
    with av.open(str(result.path)) as c:
        frames = list(c.decode(video=0))
        assert float(frames[0].pts * frames[0].time_base) == pytest.approx(0, abs=.002)
        assert float(frames[-1].pts * frames[-1].time_base) == pytest.approx(duration - duration/240, abs=.002)
    with av.open(str(result.path)) as c:
        sound = list(c.decode(audio=0))
        samples = np.concatenate([f.to_ndarray().reshape(-1) for f in sound])
        segment = samples[48000:96000]
        peak = np.argmax(abs(np.fft.rfft(segment * np.hanning(len(segment))))) * 48000 / len(segment)
        assert peak == pytest.approx(440, abs=2)
        assert len(samples)/48000 == pytest.approx(duration, abs=.05)


@pytest.mark.parametrize("ext,codec", [(".mp4","libx264"), (".mov","prores_ks"), (".mkv","libx264"), (".avi","mpeg4"), (".webm","libvpx-vp9")])
def test_silent_containers_preserve_video(make_video, tmp_path, ext, codec):
    src = make_video(name="silent"+ext, audio=False, frames=48, codec=codec)
    result = convert(src, Fraction(30), tmp_path)
    assert inspect_media(result.path).frame_count == 48
    assert packet_hash(result.path) == packet_hash(src)


def test_no_overwrite_and_repeat_export(make_video, tmp_path):
    src = make_video(frames=24, audio=False)
    a = convert(src, Fraction(30), tmp_path)
    before = a.path.read_bytes()
    b = convert(src, Fraction(30), tmp_path)
    assert a.path != b.path != src
    assert a.path.read_bytes() == before
    assert not list(tmp_path.glob(".fps-tools-*"))


def test_cancel_keeps_only_source(make_video, tmp_path):
    src = make_video(frames=24)
    event = threading.Event()
    def progress(phase, value):
        if "导出" in phase:
            event.set()
    with pytest.raises(Cancelled):
        convert(src, Fraction(30), tmp_path, cancel=event, progress=progress)
    assert list(tmp_path.iterdir()) == [src]


def test_vfr_is_rejected(make_video, ffmpeg, tmp_path):
    src = make_video(frames=48, audio=False)
    vfr = tmp_path/"vfr.mp4"
    subprocess.run([ffmpeg,"-v","error","-i",str(src),"-vf","select=not(mod(n\\,3))+not(mod(n\\,7))",
                    "-fps_mode","vfr","-c:v","libx264",str(vfr)],check=True,capture_output=True)
    with pytest.raises(MediaError, match="可变帧率"):
        convert(vfr, Fraction(30), tmp_path)


def test_nonzero_start_is_normalized(make_video, tmp_path):
    src = make_video(frames=48, audio=False, extra=("-output_ts_offset","5"))
    out = convert(src, Fraction(30), tmp_path)
    info = inspect_media(out.path)
    assert info.start == pytest.approx(0, abs=.002)
    assert float(info.duration) == pytest.approx(1.6, abs=.002)


def test_extra_streams_refused(make_video, ffmpeg, tmp_path):
    src = make_video(frames=24, audio=False)
    multi = tmp_path/"multi.mkv"
    subprocess.run([ffmpeg,"-v","error","-i",str(src),"-map","0:v","-map","0:v","-c","copy",str(multi)],check=True,capture_output=True)
    with pytest.raises(MediaError, match="视频轨道"):
        convert(multi, Fraction(30), tmp_path)


def test_broken_file_is_rejected(tmp_path):
    path = tmp_path/"broken.mp4"
    path.write_bytes(b"not a video")
    with pytest.raises(MediaError):
        inspect_media(path)


def test_same_rate_copies_file_without_audio_reencoding(make_video, tmp_path):
    src = make_video(frames=48)
    result = convert(src, Fraction(24), tmp_path)
    assert result.path.read_bytes() == src.read_bytes()


@pytest.mark.parametrize("offset", ["0", "5"])
def test_two_audio_tracks_preserve_relative_delay_and_pitch(make_video, ffmpeg, tmp_path, offset):
    src = make_video(frames=96, audio=False)
    mixed = tmp_path / "delayed.mp4"
    subprocess.run([ffmpeg,"-v","error","-i",str(src),"-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=4",
                    "-itsoffset","0.5","-f","lavfi","-i","sine=frequency=880:sample_rate=48000:duration=3.5",
                    "-map","0:v","-map","1:a","-map","2:a","-c:v","copy","-c:a","aac",
                    "-output_ts_offset",offset,str(mixed)],check=True,capture_output=True)
    result = convert(mixed, Fraction(30), tmp_path)
    with av.open(str(result.path)) as c:
        assert len(c.streams.audio) == 2
        delayed = c.streams.audio[1]
        frames = list(c.decode(delayed))
        assert float(frames[0].pts * frames[0].time_base) == pytest.approx(.4, abs=.05)
        samples = np.concatenate([f.to_ndarray().reshape(-1) for f in frames])
        segment = samples[48000:96000]
        peak = np.argmax(abs(np.fft.rfft(segment*np.hanning(len(segment))))) * 48000/len(segment)
        assert peak == pytest.approx(880,abs=2)


def test_ntsc_source_to_30_has_exact_duration(make_video, tmp_path):
    src = make_video(fps="24000/1001", frames=240)
    out = convert(src, Fraction(30), tmp_path)
    assert inspect_media(out.path).duration == 8


@pytest.mark.parametrize("target", ["1","240"])
def test_extreme_targets_keep_all_frames(make_video, tmp_path, target):
    src = make_video(frames=24)
    out = convert(src, Fraction(target), tmp_path)
    assert inspect_media(out.path).frame_count == 24


def test_refuses_disguised_truncated_file(make_video, tmp_path):
    src = make_video(frames=48, extra=("-movflags","+faststart"))
    src.write_bytes(src.read_bytes()[:-2000])
    with pytest.raises(MediaError):
        convert(src, Fraction(30), tmp_path)
