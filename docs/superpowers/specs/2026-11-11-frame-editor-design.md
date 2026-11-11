# FPS Tools Studio 2.0 — frame rhythm editor

## Intent and decisions

The user wants a separate new version while retaining v1.1.0, with every source frame visible on a scrollable filmstrip. They choose frames to delete or repeat to control limited-animation timing, preview the result, and export at a chosen frame rate. In a second mode the tool proposes drops/repeats for a new frame rate at the original duration; the user moves those choices to preserve motion accents.

The user explicitly relaxed the original no-reencoding requirement for this module: selectable H.264 (default **100 Mbps**, editable) and ProRes **422 HQ** are sufficient. The new editor is high-quality reencoding, never advertised as bit-identical. The original packet-copy conform tool remains available unchanged. v1.1.0 release/tag and local stable checkout remain intact.

## Approach

Continue PySide6 + PyAV + bundled FFmpeg, adding Qt Multimedia for audio preview. Implement a focused frame/exposure model rather than importing a full NLE. Investigated libopenshot (Qt player/Python editing API), MLT (general editing framework), LosslessCut (primarily stream-copy segment cutting), Frame Checker (inspection rather than editing). Full editing engines add another packaging/media pipeline and do not supply the desired exact exposure UI. The existing stack already scans frames, validates media and builds on three platforms.

Sources: https://github.com/OpenShot/libopenshot , https://github.com/mltframework/mlt , https://github.com/mifi/lossless-cut , https://github.com/kuvk/frame-checker , https://pyav.org/ , https://ffmpeg.org/ffmpeg-codecs.html#ProRes .

## Interaction

- New standalone application name **FPS Tools Studio**, separate bundle ID and package folder; release 2.0.0. Tabs: **逐帧编辑** and **原帧率工具** (v1.1 engine and UI retained).
- Import one CFR video at a time. Source is never overwritten. Inspect using the existing validated media reader; report unsupported or corrupt media clearly.
- Upper preview with current source/output frame number, previous/next, play/pause, loop, frame seek and playback time. Preview uses cached scaled images; exports always decode original-resolution source frames.
- Two horizontal, virtualized filmstrips: original frames, marked **删除** (0), **保留** (1), **重复 ×N** (>1), and the actual output frame sequence. Clicking either selects the corresponding frame and updates preview. Ctrl/Shift multi-selection supported on source strip. Zoom controls change thumbnail size.
- Actions: delete selected, duplicate selected (one additional exposure each), restore selected, repeat-count input/apply, move an exposure/deletion decision to previous/next source frame, undo/redo. No interpolation or generated in-between images.
- Free mode changes total frame count and resulting duration. Keep-duration mode generates exactly `round_half_up(N * target_fps/source_fps)` output frames (minimum 1). 100@24→12 is 50; →30 is 125. When the number is fractional, display actual duration and signed rounding difference.
- Keep-duration edits may temporarily unbalance the target count; show missing/excess frames and disable export until reconciled. Moving one exposure between neighboring frames preserves the count. Never silently compensate by changing unrelated frames.
- Save/open `.fpsedit` projects containing source reference/fingerprint and edit settings, not video frames. Validate source identity on reopen; allow locating the same media if moved. Unsaved changes receive a normal save/discard/cancel prompt on replacing/closing a project.

## Model and cache

An immutable plan stores a nonnegative repetition count for each source frame. Output order is source order; repeated frames are adjacent exposures. Prefix sums map an output index back to its source frame without expanding millions of Python objects. Undo/redo tracks immutable plans, capped at 100 entries. Source numbering displayed to humans is 1-based; internal indices 0-based.

Import generates disk-backed 640px previews and 144px thumbnails in a per-session temporary directory in a background worker; no full-resolution frame arrays are retained. GUI caches are bounded. Cancelling/importing another source closes workers before disposing their cache. The cache is used only for preview, never final export. Large/long videos show import progress, bounded memory, and cancellation.

## Export

- H.264 MP4, software libx264, default 100 Mbps, configurable 1–500 Mbps, source dimensions, 8-bit or 10-bit according to source. Chroma conversion is permitted by the selected codec; dimensions never silently resized. Unsupported odd dimensions/alpha/HDR conversions must be explained rather than silently flattened.
- ProRes 422 HQ MOV, `prores_ks` profile 3, 10-bit 4:2:2, source dimensions. It is profile-based rather than user-set bitrate. Preserve meaningful color tags and display orientation; clearly identify precision/alpha limitations before export.
- Decode each source frame once and encode it zero/one/multiple times from plan repetitions with exact rational target timestamps. Verify output frame count, codec/profile, dimensions, fps and timeline before atomic no-overwrite publication. Packet hashes cannot match after reencoding; do not apply the original conform tool's packet-copy integrity claim to this path.
- Export uses cancellable background jobs, temporary video/output files and collision-safe publication. No partial final output on failure/cancel; source identity rechecked.
- Audio choices: **原时间轴** (trim/pad to result duration), **整体变速不变调** (stretch source timeline to new total duration), **静音**. Keep-duration defaults to original timeline; free mode defaults to tempo. These are whole-track policies, not automatic per-frame audio cutting. Preserve all audio tracks in export; first track used for preview. H.264 exports AAC; ProRes exports PCM. Existing audio gap protection stays in place.
- Preview audio rendered to a small PCM cache matching the chosen policy; playback is available immediately for video, audio preparation status is explicit. Edits pause playback; no stale plan audio plays after edits. In environments without an audio device video preview still works.

## Boundaries and acceptance

This is a single-source frame rhythm editor, not a multi-track compositor. No effects, arbitrary frame reorder, interpolation, optical flow, or claims that H.264/ProRes are lossless. Existing timecode/subtitle limitations remain explicit on import. Supported SDR input bit depth/alpha constraints are shown; no silent HDR tone conversion.

Acceptance: real 100-frame fixtures verify exact 50/125 frame plans and editable choices; export recognizable frames after deletion/duplication and verify sequence, duration, profile and sound policy. Exercise undo/redo, project save/reopen, cache cancellation/cleanup, noninteger duration, source mutation, Unicode paths, small window and all old tests. Test packaged Mac arm64, Mac Intel and Windows x64. Verify actual supplied user clips locally without uploading them. Fresh final review before release; publish new ZIPs without modifying v1.1.0 assets.
