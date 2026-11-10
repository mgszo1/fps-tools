"""Frame-rate conform. Video payloads are never decoded for encoding.

Decoding is used only to validate frame counts and presentation timestamps.
The output is not published until encoded packet identity is proven.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av

from .process import Cancelled, MediaError, check_cancel, run_engine

Progress = Callable[[str, float], None]
EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
NTSC = {"23.976": Fraction(24000,1001), "29.97": Fraction(30000,1001), "59.94": Fraction(60000,1001),
        "119.88": Fraction(120000,1001)}


def parse_fps(text: str) -> Fraction:
    try:
        text = text.strip()
        if len(text) > 40:
            raise ValueError
        value = NTSC[text] if text in NTSC else Fraction(text)
        if not 1 <= value <= 240 or value.denominator > 1_000_000 or value.numerator > 240_000_000:
            raise ValueError
        return value
    except (ValueError, ZeroDivisionError, OverflowError):
        raise MediaError("请输入 1–240 之间的帧率，如 30、23.976 或 30000/1001。") from None


@dataclass(frozen=True)
class AudioInfo:
    index: int
    codec: str
    channels: int
    sample_rate: int
    start: Fraction


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    fps: Fraction
    frame_count: int
    duration: Fraction
    start: Fraction
    time_base: Fraction
    video_index: int
    codec: str
    width: int
    height: int
    properties: tuple
    packet_hash: str
    extradata: bytes
    audio: tuple[AudioInfo, ...]
    file_identity: tuple[int, int]


@dataclass(frozen=True)
class ConversionResult:
    path: Path
    frames: int
    fps: Fraction
    duration: Fraction
    video_hash: str


def _identity(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def inspect_media(path: Path | str, cancel: threading.Event | None = None,
                  progress: Progress | None = None) -> MediaInfo:
    path = Path(path).resolve()
    check_cancel(cancel)
    if path.suffix.lower() not in EXTENSIONS:
        raise MediaError("暂不支持此封装格式。请选择 MP4、MOV、M4V、MKV、AVI 或 WebM。")
    try:
        identity = _identity(path)
        with av.open(str(path)) as container:
            videos = list(container.streams.video)
            if len(videos) != 1:
                raise MediaError("目前只支持包含一个视频轨道的文件。")
            if any(s.type not in {"video", "audio"} for s in container.streams) or container.chapters():
                raise MediaError("此文件含字幕、章节或数据轨道；为避免丢失信息，暂不处理。")
            stream = videos[0]
            rate = stream.average_rate or stream.guessed_rate or stream.base_rate
            if rate is None or rate <= 0:
                raise MediaError("无法确定原始帧率。")
            rate, tb = Fraction(rate), Fraction(stream.time_base)
            audio = tuple(AudioInfo(s.index, s.codec_context.name, s.codec_context.channels,
                                     s.codec_context.sample_rate,
                                     Fraction(s.start_time or 0) * s.time_base)
                          for s in container.streams.audio)
            ctx = stream.codec_context
            properties = (ctx.name, ctx.width, ctx.height, ctx.pix_fmt,
                          ctx.color_range, ctx.color_primaries, ctx.color_trc, ctx.colorspace,
                          str(stream.sample_aspect_ratio))
            extradata = bytes(ctx.extradata or b"")
            stream.thread_type = "AUTO"
            digest = hashlib.sha256()
            count = 0
            first = None
            previous = None
            total = stream.frames or 0
            tolerance = max(tb * Fraction(11,10), Fraction(1,1_000_000))
            ends: dict[int, Fraction] = {}
            for packet in container.demux():
                check_cancel(cancel)
                if packet.is_corrupt:
                    raise MediaError("检测到损坏或不完整的数据包，无法保证完整导出。")
                if packet.size and packet.pts is not None and packet.duration:
                    end = Fraction(packet.pts + packet.duration) * packet.time_base
                    ends[packet.stream.index] = max(ends.get(packet.stream.index, end), end)
                if packet.stream.index != stream.index:
                    continue
                if packet.size:
                    # Matroska legitimately omits the first DTS values for B frames.
                    # Decoded presentation timing plus payload identity is authoritative.
                    if packet.pts is None:
                        raise MediaError("视频时间戳不完整，无法保证无损改帧率。")
                    digest.update(packet.size.to_bytes(8, "big"))
                    digest.update(bytes(packet))
                for frame in packet.decode():
                    if frame.is_corrupt:
                        raise MediaError("检测到损坏的视频帧。")
                    if frame.pts is None:
                        raise MediaError("视频缺少帧时间戳。")
                    stamp = Fraction(frame.pts) * frame.time_base
                    if first is None:
                        first = stamp
                    if (previous is not None and stamp <= previous) or abs(stamp - first - count/rate) > tolerance:
                        raise MediaError("检测到可变帧率或不连续时间戳。当前版本只处理恒定帧率视频。")
                    previous = stamp
                    count += 1
                    if progress and count % 48 == 0:
                        progress("检查视频", min(.99, count/total) if total else 0.)
            if not count or first is None:
                raise MediaError("没有可读取的视频帧。")
            if total and total != count:
                raise MediaError("实际帧数与文件索引不一致，文件可能不完整。")
            for s in container.streams.audio:
                if s.duration and s.start_time is not None:
                    expected_end = (s.start_time + s.duration) * s.time_base
                    if ends.get(s.index, Fraction(0)) + 2*s.time_base < expected_end:
                        raise MediaError("音轨数据不完整，文件可能被截断。")
            if _identity(path) != identity:
                raise MediaError("检查期间源文件发生变化，请重新添加。")
            return MediaInfo(path, rate, count, count/rate, first, tb, stream.index, ctx.name,
                             ctx.width, ctx.height, properties, digest.hexdigest(), extradata, audio, identity)
    except (MediaError, Cancelled):
        raise
    except (av.FFmpegError, OSError, ValueError) as error:
        raise MediaError(f"无法完整读取视频：{error}") from error


def _tempo_filters(speed: Fraction) -> str:
    value = float(speed)
    stages = []
    while value > 2:
        stages.append("atempo=2")
        value /= 2
    while value < .5:
        stages.append("atempo=0.5")
        value *= 2
    stages.append(f"atempo={value:.15g}")
    return ",".join(stages)


def _audio_options(info: MediaInfo, target: Fraction) -> list[str]:
    options = []
    speed = target / info.fps
    duration = info.frame_count/target
    encoders = {"aac": "aac", "mp3": "libmp3lame", "opus": "libopus", "vorbis": "libvorbis",
                "ac3": "ac3", "eac3": "eac3", "flac": "flac", "alac": "alac"}
    for i, audio in enumerate(info.audio):
        codec = encoders.get(audio.codec)
        if audio.codec.startswith("pcm_"):
            codec = audio.codec
        if codec is None:
            raise MediaError(f"音频编码 {audio.codec} 暂不支持保持原编码的变速处理。")
        delay = max(Fraction(0), audio.start - info.start) / speed
        trim = max(Fraction(0), info.start - audio.start)
        if delay >= duration:
            raise MediaError("音轨起点位于视频结束之后，无法自动对齐。")
        filters = (f"asetpts=PTS-STARTPTS,atrim=start={float(trim):.15g},asetpts=PTS-STARTPTS,"
                   f"{_tempo_filters(speed)},apad,atrim=duration={float(duration-delay):.15g},"
                   f"asetpts=PTS+{float(delay):.15g}/TB")
        options += [f"-filter:a:{i}", filters, f"-c:a:{i}", codec]
        if audio.codec == "aac":
            options += [f"-b:a:{i}", f"{min(768, 192*audio.channels)}k"]
        elif audio.codec == "mp3":
            options += [f"-q:a:{i}", "0"]
        elif audio.codec == "vorbis":
            options += [f"-q:a:{i}", "8"]
        elif audio.codec in {"opus", "ac3", "eac3"}:
            options += [f"-b:a:{i}", f"{min(512, 128*audio.channels)}k"]
    return options


def _publish(temp: Path, source: Path, target: Fraction, directory: Path) -> Path:
    label = str(target).replace("/", "-")
    base = f"{source.stem}_{label}fps"
    for n in range(1, 100_000):
        suffix = "" if n == 1 else f"_{n}"
        path = directory / f"{base}{suffix}{source.suffix}"
        try:
            # Reserve without overwriting any existing name, then atomically replace our reservation.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        try:
            os.replace(temp, path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
    raise MediaError("同名输出文件过多，请选择其他文件夹。")


def convert(source: Path | str, target: Fraction, directory: Path | str,
            cancel: threading.Event | None = None, progress: Progress | None = None) -> ConversionResult:
    target = parse_fps(str(target))
    source = Path(source).resolve()
    directory = Path(directory).resolve()
    report = progress or (lambda phase, value: None)
    info = inspect_media(source, cancel, lambda _, v: report("检查源视频", v * .3))
    if not directory.is_dir():
        raise MediaError("输出文件夹不存在。")
    duration = info.frame_count/target
    args = _audio_options(info, target)
    check_cancel(cancel)
    fd, name = tempfile.mkstemp(prefix=".fps-tools-", suffix=source.suffix, dir=directory)
    os.close(fd)
    temp = Path(name)
    try:
        report("正在导出", .3)
        check_cancel(cancel)
        if target == info.fps:
            with source.open("rb") as src, temp.open("wb") as dst:
                while chunk := src.read(4*1024*1024):
                    check_cancel(cancel)
                    dst.write(chunk)
        else:
            # Scale before the muxer's target-rate time-base quantization. setts
            # must preserve PTS and DTS separately, or B-frame order is corrupted.
            expr = f"setts=pts=PTS:dts=DTS:duration=1/(({target})*TB)"
            cmd = ["-y", "-err_detect", "explode", "-copyts", "-itsoffset", str(-float(info.start)),
                   "-itsscale:v", str(float(info.fps/target)), "-i", str(source),
                   "-map", f"0:{info.video_index}"]
            for audio in info.audio:
                cmd += ["-map", f"0:{audio.index}"]
            cmd += ["-map_metadata", "0", "-map_chapters", "-1", "-c:v", "copy", "-bsf:v", expr,
                    "-r:v", str(target), "-avoid_negative_ts", "disabled", *args]
            if source.suffix.lower() in {".mp4", ".mov", ".m4v"}:
                cmd += ["-video_track_timescale", str(target.numerator)]
            cmd += [str(temp)]
            run_engine(cmd, cancel, lambda v: report("正在导出", .3 + v*.35), float(duration))
        report("校验画面与帧数", .65)
        checked = inspect_media(temp, cancel, lambda _, v: report("校验画面与帧数", .65 + v*.34))
        if (checked.frame_count != info.frame_count or checked.packet_hash != info.packet_hash
                or checked.extradata != info.extradata or checked.properties != info.properties):
            raise MediaError("画面完整性校验未通过，输出已撤销。没有改用重新编码。")
        tolerance = max(checked.time_base * 2, Fraction(1, 1000))
        if abs(checked.duration-duration) > tolerance or checked.fps != target:
            raise MediaError("目标帧率或时长校验未通过，输出已撤销。")
        if len(checked.audio) != len(info.audio):
            raise MediaError("音轨完整性校验未通过，输出已撤销。")
        if _identity(source) != info.file_identity:
            raise MediaError("处理期间源文件发生变化，输出已撤销。")
        check_cancel(cancel)
        output = _publish(temp, source, target, directory)
        report("完成 · 画面校验通过", 1.)
        return ConversionResult(output, info.frame_count, target, duration, info.packet_hash)
    except OSError as error:
        raise MediaError(f"文件读写失败：{error}") from error
    finally:
        temp.unlink(missing_ok=True)
