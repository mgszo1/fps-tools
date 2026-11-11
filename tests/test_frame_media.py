from dataclasses import replace
from fractions import Fraction as F
import threading
import av
import numpy as np
import pytest
from fps_tools.media import inspect_media, MediaError
from fps_tools.process import Cancelled
from fps_tools.frame_plan import FramePlan
from fps_tools.frame_media import ExportSettings, export_frames, prepare_clip, prepare_audio_preview


def test_preview_cache(make_video,tmp_path):
    path=make_video(frames=6,audio=False)
    clip=prepare_clip(path,tmp_path/'cache')
    assert clip.info.frame_count==6
    assert all(clip.thumbnail(i).is_file() and clip.preview(i).is_file() for i in range(6))


@pytest.mark.parametrize('codec',['h264','prores'])
def test_selected_sequence_and_audio(make_video,tmp_path,codec):
    path=make_video(frames=12)
    info=inspect_media(path)
    plan=replace(FramePlan.original(12,F(24)),target_fps=F(30),repeats=(0,2,1,0,1,3,1,0,1,1,1,1))
    result=export_frames(info,plan,ExportSettings(codec=codec),tmp_path)
    got=inspect_media(result.path)
    assert got.frame_count==plan.total and got.fps==30 and len(got.audio)==1
    assert (got.width,got.height)==(160,90)
    assert got.codec==('h264' if codec=='h264' else 'prores')
    with av.open(str(path)) as c: source=[f.to_ndarray(format='rgb24').astype(float) for f in c.decode(video=0)]
    with av.open(str(result.path)) as c:
        frames=list(c.decode(video=0))
        if codec=='prores': assert c.streams.video[0].codec_context.profile=='HQ'
    for i,frame in enumerate(frames):
        pixel=frame.to_ndarray(format='rgb24').astype(float)
        expected=source[plan.source_at(i)]
        assert np.mean(np.abs(pixel-expected)) < 8
    assert info.path.is_file()


def test_cancel_source_change_and_empty(make_video,tmp_path):
    info=inspect_media(make_video(frames=5,audio=False))
    plan=FramePlan.original(5,F(24))
    event=threading.Event();event.set()
    with pytest.raises(Cancelled): export_frames(info,plan,ExportSettings(),tmp_path,cancel=event)
    with pytest.raises(MediaError): export_frames(info,plan.set_counts(range(5),0),ExportSettings(),tmp_path)
    info.path.touch()
    with pytest.raises(MediaError,match='变化'): export_frames(info,plan,ExportSettings(),tmp_path)
    assert not list(tmp_path.glob('.fps-edit-*'))


def test_preview_audio_duration_and_pitch(make_video,tmp_path):
    info=inspect_media(make_video(frames=48))
    plan=replace(FramePlan.original(48,F(24)),target_fps=F(48))
    out=tmp_path/'preview.wav'
    prepare_audio_preview(info,plan,'tempo',out)
    with av.open(str(out)) as c:
        rate=c.streams.audio[0].rate
        samples=np.concatenate([f.to_ndarray().reshape(-1) for f in c.decode(audio=0)])
    assert abs(len(samples)/rate-1)<.02
    peak=np.argmax(np.abs(np.fft.rfft(samples))) * rate/len(samples)
    assert abs(peak-440)<5


def test_ten_bit_prores_and_rotation(make_video,tmp_path,ffmpeg):
    import subprocess
    original=make_video(frames=6,audio=False)
    rotated=tmp_path/'rotated.mp4'
    subprocess.run([ffmpeg,'-y','-i',str(original),'-c','copy','-metadata:s:v:0','rotate=90',str(rotated)],check=True,capture_output=True)
    info=inspect_media(rotated)
    plan=FramePlan.original(6,F(24))
    output=export_frames(info,plan,ExportSettings('prores'),tmp_path)
    with av.open(str(rotated)) as c: rotation=next(c.decode(video=0)).rotation
    with av.open(str(output.path)) as c:
        frame=next(c.decode(video=0))
        assert frame.rotation==rotation
        assert frame.format.name=='yuv422p10le'
    # The ProRes output itself is a valid 10-bit input for another edit.
    got=export_frames(inspect_media(output.path),plan,ExportSettings('h264'),tmp_path)
    with av.open(str(got.path)) as c: assert next(c.decode(video=0)).format.name=='yuv420p10le'


def test_mid_export_cancel_cleanup(make_video,tmp_path):
    info=inspect_media(make_video(frames=12,audio=False))
    event=threading.Event()
    def progress(message,value):
        if value>.1: event.set()
    with pytest.raises(Cancelled):
        export_frames(info,FramePlan.original(12,F(24)),ExportSettings(),tmp_path,event,progress)
    assert not list(tmp_path.glob('*edited*')) and not list(tmp_path.glob('.fps-edit-*'))
