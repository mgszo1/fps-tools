from fractions import Fraction as F
from dataclasses import replace
import json
import pytest
from fps_tools.frame_plan import FramePlan, FrameHistory, resample_plan, save_project, load_project
from fps_tools.media import inspect_media, MediaError


def test_resampling_and_rounding():
    assert resample_plan(100,F(24),F(12)).total == 50
    assert resample_plan(100,F(24),F(30)).total == 125
    assert resample_plan(97,F(24),F(12)).total == 49
    p = resample_plan(121,F(24),F(30))
    assert p.total == 151 and p.duration_error == -F(1,120)
    assert all(0 <= p.source_at(i) < 121 for i in range(p.total))


def test_edits_mapping_balance_history():
    p = FramePlan.original(4,F(24))
    q = p.set_counts([1],0).increment([2],2)
    assert q.repeats == (1,0,3,1)
    assert [q.source_at(i) for i in range(5)] == [0,2,2,2,3]
    assert q.transfer(2,1).repeats == (1,1,2,1)
    h = FrameHistory(p); h.push(q); assert h.undo() == p; assert h.redo() == q
    h.undo(); h.push(p.increment([0])); assert h.redo() == h.current
    locked = replace(q, keep_duration=True)
    assert locked.balance == 1 and not locked.exportable
    assert not p.set_counts(range(4),0).exportable
    with pytest.raises(IndexError): q.source_at(5)
    with pytest.raises(MediaError): p.set_counts([0],-1)
    with pytest.raises(MediaError): p.increment([0],1_000_001)


def test_project_roundtrip_validation(make_video,tmp_path):
    info=inspect_media(make_video(frames=12,audio=False))
    plan=resample_plan(12,F(24),F(30))
    dest=tmp_path/'edit.fpsedit'
    save_project(dest,info,plan,{'codec':'h264','bitrate_mbps':100,'audio_mode':'tempo'})
    data=load_project(dest)
    assert data.plan==plan and data.source==info.path
    assert data.fingerprint==info.packet_hash
    obj=json.loads(dest.read_text()); obj['repeats'][0]=True
    dest.write_text(json.dumps(obj))
    with pytest.raises(MediaError): load_project(dest)
