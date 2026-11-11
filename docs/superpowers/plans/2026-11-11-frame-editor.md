# FPS Tools Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline; one fresh whole-branch review at the end. Steps use checkbox syntax.

**Goal:** Deliver a separate portable frame-editing version with exposure editing, editable duration-preserving resampling and H.264/ProRes export.
**Architecture:** immutable exposure plan → disk-backed preview worker → virtualized Qt filmstrips/player; original frames → new encoding/export service. A Studio shell retains the existing conform window as a second tab.
**Tech Stack:** Python 3.11, PySide6 6.12 (Essentials + Addons), PyAV 18.1, bundled FFmpeg, PyInstaller.
**Spec:** `docs/superpowers/specs/2026-11-11-frame-editor-design.md`

## Global Constraints

- Preserve v1.1.0 release and original packet-copy tool; develop in the independent Studio worktree.
- H.264 default 100 Mbps (1–500 configurable), ProRes 422 HQ profile 3; explicit reencoding, no lossless claim.
- Every output frame references one source frame; no interpolation. Source dimensions preserved. Source never overwritten.
- Keep-duration target uses nearest integer, half-up, minimum 1; display rounding error and unresolved frame-count balance.
- Preview/cache and export run in cancellable background jobs with bounded memory. Export decodes original frames.
- Mac arm64/x64 and Windows x64, offline portable ZIPs; never upload user clips.

## Review Focus

- Fractional rates, all-deleted plans, huge copy counts and malformed project JSON must not cause invalid exports or resource explosions.
- Source changes and cache disposal while jobs run must not produce mixed or stale media.
- Lossy codec output must match the requested source-frame sequence; bit depth, alpha, orientation and color tags must be explicit.
- Audio preview must follow current settings and pause on edits; export tracks must honor the displayed policy.
- Long filmstrips, rapid selection, narrow windows and closing during background work must remain responsive and safe.

### Task 1: Exposure model and project persistence

**Files:** create `fps_tools/frame_plan.py`, `tests/test_frame_plan.py`.
**Interfaces:** `FramePlan(source_frames, source_fps, target_fps, repeats, keep_duration)`, `resample_plan(n, source_fps, target_fps)`, `FrameHistory`, `save_project(path, info, plan, settings)`, `load_project(path)`.
- [ ] Write failing tests: 100@24→12/30 gives 50/125, edit/transfer preserves intended counts, mapping/prefix boundaries, half-up rounding, undo/redo, empty plan blocked for export, JSON validation and source fingerprint serialization.
- [ ] Run `.venv/bin/python -m pytest tests/test_frame_plan.py -q`; expected initial import failure, then implement and get PASS.
- [ ] Commit model.

### Task 2: Preview media and edited export

**Files:** create `fps_tools/frame_media.py`, `tests/test_frame_media.py`; use existing `media.py`/`process.py` without weakening conform checks.
**Interfaces:** `prepare_clip(path, cache_dir, cancel, progress)->PreparedClip`, `export_frames(info, plan, settings, directory, cancel, progress)->EditResult`, `prepare_audio_preview(info, plan, mode, path, cancel)`; dataclasses `ExportSettings(codec, bitrate_mbps, audio_mode)` and `PreparedClip(info, cache_dir)`.
- [ ] Write failing real-media tests for proxies, exact selected/duplicated frame sequence in H.264/ProRes, dimensions/profile, pitch and duration policies, cancellation/source mutation/temporary cleanup, depth/orientation.
- [ ] Implement sequential original-frame encoding with rational PTS, profile validation, explicit format constraints, FFmpeg audio mux and checked atomic publication. Preview JPEG cache never enters export.
- [ ] Run `.venv/bin/python -m pytest tests/test_frame_media.py tests/test_media.py -q`; expected PASS. Commit.

### Task 3: Frame editor and preview UI

**Files:** create `fps_tools/frame_widgets.py`, `fps_tools/frame_editor.py`, `tests/test_frame_editor.py`; add QtMultimedia dependency.
**Interfaces:** `FrameEditor(QWidget)` with busy/cancel lifecycle, `FilmstripModel` source/output views and bounded pixmap cache; consumes Tasks 1/2 dataclasses and APIs.
- [ ] Write failing GUI tests for import, single/multiple edit, neighboring exposure transfer, undo/redo, duration lock, project save/reopen and asynchronous export. Include small-window geometry and close/cancel cleanup.
- [ ] Implement dual virtualized strips, big preview, playback/step/loop, selection controls, encoding/audio settings, progress/log, project actions. Source/output index identities remain distinct.
- [ ] Run `.venv/bin/python -m pytest tests/test_frame_editor.py -q`; expected PASS. Visually inspect real UI and export a user clip. Commit.

### Task 4: Studio shell and portable release

**Files:** create `fps_tools/studio.py`; modify launch/version/build/smoke/README/workflow as needed; add startup coverage.
**Interfaces:** `StudioWindow` owns legacy and editor lifecycle; `main()` initializes Studio, packaged smoke exercises both paths.
- [ ] Add failing shell/startup tests, then integrate tabs and new application name/bundle ID. Retain original tool tests.
- [ ] Run full suite, local packaged smoke, user-clip edit verification. Expected all PASS.
- [ ] Fresh final review of whole branch; fix important findings with RED→GREEN tests and a green whole suite.
- [ ] Push authorized new branch/release, complete three-platform native CI, verify/upload ZIP checksums, publish 2.0.0 while retaining 1.1.0.
