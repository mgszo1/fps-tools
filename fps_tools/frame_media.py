"""Disk-backed viewing proxies and source-resolution exposure rendering."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import os
from pathlib import Path
import struct
import tempfile

import av
from PySide6.QtGui import QImage, QTransform
from .media import MediaInfo, inspect_media, _identity, _tempo_filters
from .frame_plan import FramePlan
from .process import MediaError, check_cancel, run_engine


@dataclass(frozen=True)
class ExportSettings:
    codec: str = 'h264'
    bitrate_mbps: int = 100
    audio_mode: str = 'tempo'

    def __post_init__(self):
        if (self.codec not in {'h264','prores'} or type(self.bitrate_mbps) is not int
                or not 1 <= self.bitrate_mbps <= 500
                or self.audio_mode not in {'tempo','original','mute'}):
            raise MediaError('导出设置无效。')


@dataclass(frozen=True)
class PreparedClip:
    info: MediaInfo
    cache_dir: Path
    def preview(self, i): return self.cache_dir / f'p{i:08d}.jpg'
    def thumbnail(self, i): return self.cache_dir / f't{i:08d}.jpg'


@dataclass(frozen=True)
class EditResult:
    path: Path
    frames: int
    fps: Fraction
    duration: Fraction


def _unchanged(info):
    if _identity(info.path)!=info.file_identity: raise MediaError('原文件已发生变化，请重新打开。')


def _format_check(info):
    fmt=av.VideoFormat(info.properties[3])
    depth=max(c.bits for c in fmt.components)
    if fmt.has_palette or any(c.is_alpha for c in fmt.components) or depth>10:
        raise MediaError('此素材包含透明通道或超过 10 位精度；当前 H.264 / ProRes 422 HQ 不适合保留这些信息。')
    if info.properties[6] in {16,18}:
        raise MediaError('HDR 素材暂不进入帧编辑，以免预览或导出产生错误的亮度转换。原帧率工具仍可使用。')
    if info.width % 2 or info.height % 2:
        raise MediaError('当前帧编辑编码要求偶数宽高；不会自动裁剪或缩放原片。')
    return depth


def prepare_clip(path, cache_dir, cancel=None, progress=None):
    progress=progress or (lambda *_:None)
    info=inspect_media(path,cancel,lambda m,p:progress('检查原片 · '+m,p*.35))
    _format_check(info)
    if info.frame_count>1_000_000: raise MediaError('帧编辑最多支持 100 万原始帧。')
    cache_dir=Path(cache_dir); cache_dir.mkdir(parents=True,exist_ok=True)
    clip=PreparedClip(info,cache_dir)
    try:
        with av.open(str(info.path)) as container:
            stream=container.streams.video[0];stream.thread_type='AUTO'
            for i,frame in enumerate(container.decode(stream)):
                check_cancel(cancel)
                scale=min(1,640/max(frame.width,frame.height))
                rgb=frame.reformat(width=max(1,int(frame.width*scale)),height=max(1,int(frame.height*scale)),format='rgb24')
                img=QImage(bytes(rgb.planes[0]),rgb.width,rgb.height,rgb.planes[0].line_size,QImage.Format.Format_RGB888).copy()
                if frame.rotation: img=img.transformed(QTransform().rotate(-frame.rotation))
                if not img.save(str(clip.preview(i)),'JPEG',92): raise MediaError('预览缓存写入失败。')
                if not img.scaledToWidth(144).save(str(clip.thumbnail(i)),'JPEG',85): raise MediaError('缩影缓存写入失败。')
                progress('生成逐帧缩影',.35+.65*(i+1)/info.frame_count)
        _unchanged(info)
        return clip
    except BaseException:
        for p in cache_dir.glob('*.jpg'): p.unlink(missing_ok=True)
        raise


def _audio_filter(info, audio, plan, mode):
    speed=(info.frame_count/info.fps)/plan.duration if mode=='tempo' else Fraction(1)
    trim=max(Fraction(0),info.start-audio.start)
    delay=max(Fraction(0),audio.start-info.start)/speed
    # Delay represented by silence so preview and mux use an identical zero-based timeline.
    return (f'asetpts=PTS-STARTPTS,atrim=start={float(trim):.12g},asetpts=PTS-STARTPTS,'
            f'{_tempo_filters(speed)},adelay={float(delay)*1000:.9g}:all=1,apad,'
            f'atrim=duration={float(plan.duration):.12g},asetpts=PTS-STARTPTS')


def prepare_audio_preview(info, plan, mode, path, cancel=None):
    if not info.audio or mode=='mute' or not plan.total: return None
    if mode not in {'tempo','original'}: raise MediaError('音频方式无效。')
    _unchanged(info)
    try:
        run_engine(['-y','-i',str(info.path),'-map',f'0:{info.audio[0].index}',
                    '-af',_audio_filter(info,info.audio[0],plan,mode),'-vn','-ac','1',
                    '-ar','48000','-c:a','pcm_s16le',str(path)],cancel)
        _unchanged(info)
        return Path(path)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def export_frames(info, plan, settings, directory, cancel=None, progress=None):
    progress=progress or (lambda *_:None)
    check_cancel(cancel); _unchanged(info)
    if plan.source_frames!=info.frame_count or plan.source_fps!=info.fps or not plan.exportable:
        raise MediaError('帧方案为空、与原片不一致，或保持时长的帧数尚未平衡。')
    depth=_format_check(info)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    suffix='.mp4' if settings.codec=='h264' else '.mov'
    with tempfile.TemporaryDirectory(prefix='.fps-edit-',dir=directory) as tmp:
        video=Path(tmp)/('video'+suffix)
        final=Path(tmp)/('final'+suffix)
        with av.open(str(info.path)) as source, av.open(str(video),'w') as out:
            src=source.streams.video[0];src.thread_type='AUTO'
            stream=out.add_stream('libx264' if settings.codec=='h264' else 'prores_ks',rate=plan.target_fps)
            stream.width=info.width;stream.height=info.height
            stream.pix_fmt=('yuv420p10le' if depth>8 else 'yuv420p') if settings.codec=='h264' else 'yuv422p10le'
            ctx=stream.codec_context
            ctx.time_base=Fraction(1,1)/plan.target_fps
            stream.time_base=ctx.time_base
            ctx.thread_count=4
            if settings.codec=='h264':
                ctx.bit_rate=settings.bitrate_mbps*1_000_000
                ctx.options={'preset':'medium'}
            else: ctx.options={'profile':'3'}
            for field,value in zip(('color_range','color_primaries','color_trc','colorspace'),info.properties[4:8]):
                setattr(ctx,field,value)
            if src.sample_aspect_ratio: ctx.sample_aspect_ratio=src.sample_aspect_ratio
            index=0;seen=0
            for i,frame in enumerate(source.decode(src)):
                check_cancel(cancel)
                if i>=plan.source_frames: raise MediaError('原片帧数发生变化。')
                if i==0:
                    for side in frame.side_data:
                        if side.type.name=='DISPLAYMATRIX': stream.set_display_matrix(struct.unpack('=9i',bytes(side)))
                seen+=1
                for _ in range(plan.repeats[i]):
                    check_cancel(cancel)
                    converted=frame.reformat(format=stream.pix_fmt)
                    converted.pts=index;converted.time_base=ctx.time_base
                    converted.pict_type=0
                    for packet in stream.encode(converted): out.mux(packet)
                    index+=1
                progress('编码原始画面',(i+1)/plan.source_frames*.75)
            if seen!=plan.source_frames: raise MediaError('原片帧数发生变化。')
            for packet in stream.encode(): out.mux(packet)
        check_cancel(cancel)
        if info.audio and settings.audio_mode!='mute':
            args=['-y','-i',str(video),'-i',str(info.path),'-map','0:v:0','-c:v','copy','-map_metadata','0']
            for i,audio in enumerate(info.audio):
                args+=['-map',f'1:{audio.index}',f'-filter:a:{i}',_audio_filter(info,audio,plan,settings.audio_mode),
                       f'-c:a:{i}','aac' if settings.codec=='h264' else 'pcm_s24le']
                if settings.codec=='h264': args += [f'-b:a:{i}',f'{min(768,192*audio.channels)}k']
            args += [str(final)]
            run_engine(args,cancel,lambda p:progress('处理声音',.75+.15*p),float(plan.duration))
        else: os.replace(video,final)
        progress('检查输出帧数与时间轴',.92)
        got=inspect_media(final,cancel)
        if (got.frame_count!=plan.total or got.fps!=plan.target_fps
                or (got.width,got.height)!=(info.width,info.height)
                or abs(got.duration-plan.duration)>got.time_base
                or len(got.audio)!=(len(info.audio) if settings.audio_mode!='mute' else 0)
                or got.codec!=('h264' if settings.codec=='h264' else 'prores')):
            raise MediaError('输出校验未通过，未保存结果。')
        check_cancel(cancel);_unchanged(info)
        label=str(plan.target_fps).replace('/','-')
        for n in range(1,100000):
            path=directory/f'{info.path.stem}_edited_{label}fps{("_"+str(n)) if n>1 else ""}{suffix}'
            try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o666)
            except FileExistsError: continue
            os.close(fd)
            try: os.replace(final,path)
            except BaseException: path.unlink(missing_ok=True);raise
            progress('导出完成',1)
            return EditResult(path,plan.total,plan.target_fps,plan.duration)
        raise MediaError('同名文件过多，请更换输出文件夹。')
