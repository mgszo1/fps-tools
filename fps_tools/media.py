"""Frame-rate conform. Video payloads are never decoded for encoding.

Decoding is used only to validate frame counts and presentation timestamps.
The output is not published until encoded packet identity is proven.
"""
from __future__ import annotations

import hashlib
import os
import re
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
        if len(text) > 40 or not re.fullmatch(r"(?:[0-9]{1,9}(?:\.[0-9]{1,6})?|[0-9]{1,9}/[0-9]{1,9})", text):
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
    timecode: str | None


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
            stream = videos[0]
            # The MOV demuxer exposes tmcd tracks as data with a timecode tag
            # and no decoder. They are regenerated at the conformed frame rate.
            extras = [s for s in container.streams if s.type not in {"video", "audio"}]
            timecode = stream.metadata.get("timecode")
            if (container.chapters() or any(
                    path.suffix.lower() not in {".mov", ".mp4", ".m4v"}
                    or s.type != "data" or s.codec_context is not None
                    or not timecode or s.metadata.get("timecode") != timecode
                    for s in extras) or len(extras) > 1):
                raise MediaError("此文件含暂不支持的字幕、章节或数据轨道；标准 MOV 时间码轨道可以处理。")
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
            last_frame_duration = None
            total = stream.frames or 0
            tolerance = min(max(tb * Fraction(11,10), Fraction(1,1_000_000)), Fraction(49,100)/rate)
            ends: dict[int, Fraction] = {}
            timecode_span = None
            # Audio timing is best-effort: inspect only video/timecode packets.
            # FFmpeg handles audio decoding during export, without rejecting files
            # merely for gaps, missing packet timestamps, or duration metadata.
            for packet in container.demux([stream, *extras]):
                check_cancel(cancel)
                if packet.is_corrupt:
                    raise MediaError("检测到损坏或不完整的数据包，无法保证完整导出。")
                if packet.size and packet.stream.type == "data":
                    if (timecode_span is not None or packet.size != 4
                            or packet.pts is None or not packet.duration):
                        raise MediaError("此 MOV 包含多段或特殊时间码，暂不能完整保留；未生成输出。")
                    timecode_span = (packet.pts * packet.time_base,
                                     (packet.pts + packet.duration) * packet.time_base)
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
                    last_frame_duration = Fraction(frame.duration or 0) * frame.time_base
                    count += 1
                    if progress and count % 48 == 0:
                        progress("检查视频", min(.99, count/total) if total else 0.)
            if not count or first is None:
                raise MediaError("没有可读取的视频帧。")
            if total and total != count:
                raise MediaError("实际帧数与文件索引不一致，文件可能不完整。")
            # Count/rate is the intended duration; compare it with an independently
            # observed presentation endpoint, including the final frame's hold time.
            actual_end = previous + last_frame_duration if last_frame_duration else ends.get(stream.index)
            if actual_end is None or abs(actual_end - first - count/rate) > tolerance:
                raise MediaError("视频末帧时长异常或无法确认，不属于可完整校验的恒定帧率视频。")
            actual_duration = actual_end - first
            if extras:
                tc_tolerance = max(tb, extras[0].time_base)
                if (timecode_span is None or abs(timecode_span[0]-first) > tc_tolerance
                        or abs(timecode_span[1]-actual_end) > tc_tolerance):
                    raise MediaError("MOV 时间码覆盖范围与视频不一致，暂不能完整保留；未生成输出。")
            if stream.duration and abs(stream.duration*tb - actual_duration) > max(2*tb,tolerance):
                raise MediaError("视频实际时长与索引不一致，文件可能不完整。")
            declared = stream.metadata.get("DURATION", "")
            match = re.fullmatch(r"([0-9]{1,5}):([0-5][0-9]):([0-5][0-9](?:\.[0-9]{1,9})?)",declared)
            if match:
                declared_end = int(match[1])*3600 + int(match[2])*60 + Fraction(match[3])
                if abs(declared_end-actual_end) > max(2*tb,tolerance):
                    raise MediaError("视频实际时长与声明时长不一致，文件可能被截断。")
            elif not audio and stream.duration is None and container.duration is not None:
                if abs(Fraction(container.duration,1_000_000)-actual_end) > max(2*tb,tolerance):
                    raise MediaError("视频实际时长与容器不一致，文件可能不完整。")
            if _identity(path) != identity:
                raise MediaError("检查期间源文件发生变化，请重新添加。")
            return MediaInfo(path, rate, count, actual_duration, first, tb, stream.index, ctx.name,
                             ctx.width, ctx.height, properties, digest.hexdigest(), extradata, audio, identity,
                             timecode if extras else None)
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
            # An unusable audio origin must not block otherwise valid video.
            delay = Fraction(0)
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


def _video_time_base(target: Fraction, suffix: str) -> Fraction:
    if suffix.lower() == ".avi":
        # AVI stores a frame clock in its stream header.
        return 1 / target
    return Fraction(1, target.numerator * min(512, 2_000_000_000 // target.numerator))


def _retime_video(info: MediaInfo, target: Fraction, destination: Path,
                  cancel: threading.Event | None, progress: Callable[[float], None]):
    """Remux packets on an exact frame grid, before any muxer quantization.

    The inspection has already proven CFR. Rational source-frame positions
    avoid accumulating millisecond rounding in MKV/WebM or rounding away
    timestamps from v1.0.0's one-tick-per-frame MP4/MOV exports.
    """
    tb = _video_time_base(target, info.path.suffix)
    try:
        with av.open(str(info.path)) as source, av.open(str(destination), "w") as output:
            original = source.streams[info.video_index]
            video = output.add_stream_from_template(original, opaque=True)
            video.codec_context.codec_tag = original.codec_context.codec_tag
            video.metadata.update(original.metadata)
            output.metadata.update(source.metadata)
            output.metadata.pop("DURATION", None)
            video.metadata.pop("DURATION", None)
            video.time_base = tb
            video.codec_context.framerate = target
            if original.sample_aspect_ratio is not None:
                video.codec_context.sample_aspect_ratio = original.sample_aspect_ratio
            output.start_encoding()
            count = 0
            for packet in source.demux(original):
                check_cancel(cancel)
                if not packet.size:
                    continue
                pts_frame = round((packet.pts * packet.time_base - info.start) * info.fps)
                dts_frame = (round((packet.dts * packet.time_base - info.start) * info.fps)
                             if packet.dts is not None else None)
                packet.pts = round(pts_frame / target / tb)
                packet.dts = round(dts_frame / target / tb) if dts_frame is not None else None
                packet.duration = round(1 / target / tb)
                packet.time_base = tb
                packet.stream = video
                output.mux(packet)
                count += 1
                if count % 48 == 0:
                    progress(min(1., count / info.frame_count))
    except av.FFmpegError as error:
        raise MediaError(f"无法在原格式内调整时间信息：{error}") from error


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
    check_cancel(cancel)
    fd, name = tempfile.mkstemp(prefix=".fps-tools-", suffix=source.suffix, dir=directory)
    os.close(fd)
    temp = Path(name)
    video_temp = None
    try:
        report("正在导出", .3)
        check_cancel(cancel)
        if target == info.fps:
            with source.open("rb") as src, temp.open("wb") as dst:
                while chunk := src.read(4*1024*1024):
                    check_cancel(cancel)
                    dst.write(chunk)
        else:
            if info.audio:
                fd, name = tempfile.mkstemp(prefix=".fps-tools-video-", suffix=source.suffix, dir=directory)
                os.close(fd)
                video_temp = Path(name)
            _retime_video(info, target, video_temp or temp, cancel,
                          lambda v: report("调整画面时间", .3 + v*.15))
            if info.audio:
                # The video clock is already correct. FFmpeg only copies it and
                # processes audio from the original file; no input time scaling.
                cmd = ["-y", "-err_detect", "explode", "-copyts", "-i", str(video_temp),
                       "-i", str(source), "-map", "0:v:0"]
                for audio in info.audio:
                    cmd += ["-map", f"1:{audio.index}"]
                args = _audio_options(info, target)
                cmd += ["-map_metadata", "1", "-map_metadata:s:v:0", "0:s:v:0", "-map_chapters", "-1",
                        "-c:v", "copy", "-r:v", str(target), "-avoid_negative_ts", "disabled", *args]
                if source.suffix.lower() in {".mp4", ".mov", ".m4v"}:
                    cmd += ["-video_track_timescale", str(_video_time_base(target, source.suffix).denominator)]
                cmd += [str(temp)]
                run_engine(cmd, cancel, lambda v: report("同步处理声音", .45 + v*.2), float(duration))
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
        if checked.timecode != info.timecode:
            raise MediaError("原时间码无法完整保留到目标帧率，输出已撤销。")
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
        if video_temp:
            video_temp.unlink(missing_ok=True)
