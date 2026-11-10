# FPS Tools 1.1 compatibility and queue fixes

> Execute inline with superpowers:executing-plans. User directly requested all five fixes and previously authorized GitHub releases.

**Spec:** User's five annotated screenshots: support MOV; drag reorder and remove individual queue items; readable small windows; source duration column; repeated frame-rate conversion. Original video packets, frame count, codec/container and pitch-preserving audio requirements continue to apply.

**Constraints:** No video encoding fallback, no dropped/added frames, no overwrite, no silent loss of unsupported tracks. Preserve integrity checks for genuinely broken/VFR input. Keep offline portable Mac arm64/x64 and Windows x64 builds.

## Review Focus

- Coarse time bases from v1.0.0, repeated slow/fast conversion, B-frame order and final-frame duration across containers.
- MOV timecode metadata: accept common professional MOV without silently losing timecode; clearly reject unsupported data rather than promise universal compatibility.
- Queue reorder/remove must preserve the row-to-source association, failure states and export order; no mutation while workers are using row indexes.
- Small windows, log expansion, DPI scaling and long paths must remain usable.

### Task 1: Media compatibility

**Files:** `fps_tools/media.py`, `tests/test_media.py`.
**Interface:** existing inspect/convert API; add explicit timecode information if necessary.

- [ ] Write regressions for legacy coarse-timebase input, 24→12→30 and repeated/NTSC conversions, MOV timecode; observe failures.
- [ ] Fix timestamp rescaling before quantization; support and verify common MOV timecode tracks.
- [ ] Run media suite, preserving damaged input and packet identity guards. Expected: all pass.
- [ ] Commit implementation and regressions.

### Task 2: Queue and responsive layout

**Files:** `fps_tools/gui.py`, `tests/test_gui.py`.
**Interface:** MediaInfo.duration supplies source duration; queue mutations update all row-indexed state only while idle.

- [ ] Add failing tests for individual remove, reorder/export association, busy guard and source duration independent of selected target.
- [ ] Implement drag reorder, individual remove and keyboard controls, source-duration column, scrollable settings with protected text/control sizes.
- [ ] Run GUI suite and inspect small-window layout. Expected: all pass, readable without overlap.
- [ ] Commit GUI fixes.

### Task 3: Verification and release

**Files:** version files, README, release notes and verification artifacts.

- [ ] Run whole suite and real user video through 24→12→30 with packet hashes/frame counts/durations checked.
- [ ] One fresh whole-branch review; fix important findings with regressions.
- [ ] Build local app and native three-platform CI; verify exact commit checks pass.
- [ ] Publish v1.1.0 ZIPs and checksums to authorized GitHub, verify release assets.
