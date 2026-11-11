"""Immutable exposures: each output frame is exactly one original source frame."""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import cached_property
import json
import os
from pathlib import Path
import tempfile

from .media import MediaError, parse_fps

MAX_FRAMES = 1_000_000


def half_up(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


@dataclass(frozen=True)
class FramePlan:
    source_frames: int
    source_fps: Fraction
    target_fps: Fraction
    repeats: tuple[int, ...]
    keep_duration: bool = False

    def __post_init__(self):
        if (type(self.source_frames) is not int or not 1 <= self.source_frames <= MAX_FRAMES
                or len(self.repeats) != self.source_frames
                or any(type(n) is not int or not 0 <= n <= 10000 for n in self.repeats)
                or sum(self.repeats) > MAX_FRAMES or type(self.keep_duration) is not bool):
            raise MediaError('帧方案无效：每帧重复次数需在 0–10000，总帧数不超过 100 万。')
        if self.source_fps <= 0 or self.source_fps > 1000:
            raise MediaError('原始帧率无效。')
        parse_fps(str(self.target_fps))

    @classmethod
    def original(cls, n, fps):
        return cls(n, Fraction(fps), Fraction(fps), (1,) * n)

    @cached_property
    def prefix(self):
        result=[0]
        for n in self.repeats:
            result.append(result[-1]+n)
        return tuple(result)

    @property
    def total(self): return self.prefix[-1]
    @property
    def desired(self): return max(1,half_up(self.source_frames*self.target_fps/self.source_fps))
    @property
    def balance(self): return self.total-self.desired
    @property
    def duration(self): return self.total/self.target_fps
    @property
    def duration_error(self): return self.duration-self.source_frames/self.source_fps
    @property
    def exportable(self): return self.total > 0 and (not self.keep_duration or self.balance == 0)

    def source_at(self, index):
        if not 0 <= index < self.total: raise IndexError(index)
        return bisect_right(self.prefix,index)-1

    def set_counts(self, indices, count):
        values=list(self.repeats)
        for i in set(indices):
            if not 0 <= i < self.source_frames: raise MediaError('选中的帧不存在。')
            values[i]=count
        return replace(self,repeats=tuple(values))

    def increment(self, indices, amount=1):
        values=list(self.repeats)
        for i in set(indices):
            if not 0 <= i < self.source_frames: raise MediaError('选中的帧不存在。')
            values[i]+=amount
        return replace(self,repeats=tuple(values))

    def transfer(self, source, destination):
        if (not 0 <= source < self.source_frames or not 0 <= destination < self.source_frames
                or abs(source-destination)!=1 or not self.repeats[source]):
            raise MediaError('请选择有曝光次数的帧，将一次曝光移给相邻帧。')
        return self.increment([source],-1).increment([destination],1)


def resample_plan(n, source_fps, target_fps):
    source_fps,target_fps=Fraction(source_fps),Fraction(target_fps)
    original=FramePlan.original(n,source_fps)
    count=replace(original,target_fps=target_fps).desired
    if count>MAX_FRAMES: raise MediaError('输出帧数超过 100 万，请降低帧率。')
    repeats=[0]*n
    # Output sample centers evenly cover the source interval. No interpolation.
    for i in range(count): repeats[min(n-1,((2*i+1)*n)//(2*count))]+=1
    return FramePlan(n,source_fps,target_fps,tuple(repeats),True)


class FrameHistory:
    def __init__(self, plan): self.items=[plan]; self.index=0
    @property
    def current(self): return self.items[self.index]
    def push(self, plan):
        if plan == self.current: return
        self.items=self.items[:self.index+1]+[plan]
        self.items=self.items[-100:]; self.index=len(self.items)-1
    def undo(self): self.index=max(0,self.index-1); return self.current
    def redo(self): self.index=min(len(self.items)-1,self.index+1); return self.current


@dataclass(frozen=True)
class Project:
    source: Path
    fingerprint: str
    plan: FramePlan
    settings: dict


def save_project(path, info, plan, settings):
    data={'version':1,'source':str(info.path),'fingerprint':info.packet_hash,
          'source_frames':plan.source_frames,'source_fps':str(plan.source_fps),
          'target_fps':str(plan.target_fps),'repeats':list(plan.repeats),
          'keep_duration':plan.keep_duration,'settings':settings}
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.fpsedit-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out: json.dump(data,out,ensure_ascii=False)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_project(path):
    try:
        path=Path(path)
        if path.stat().st_size > 12_000_000: raise ValueError()
        obj=json.loads(path.read_text(encoding='utf-8'))
        if obj['version']!=1 or not isinstance(obj['source'],str): raise ValueError()
        fp=obj['fingerprint']
        if not isinstance(fp,str) or len(fp)!=64 or any(c not in '0123456789abcdef' for c in fp): raise ValueError()
        plan=FramePlan(obj['source_frames'],parse_fps(obj['source_fps']),parse_fps(obj['target_fps']),
                       tuple(obj['repeats']),obj['keep_duration'])
        if not isinstance(obj['settings'],dict): raise ValueError()
        return Project(Path(obj['source']),fp,plan,obj['settings'])
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise MediaError('工程文件无效或损坏，未载入。') from None
