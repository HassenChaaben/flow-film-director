# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-11-15

### Added
- **Bridge-locked keyframe transitions (`bridge_from_prev`)** in `build_prompts.py`: continuous scenes automatically reuse the preceding scene's Gate-4 verified `accepted.end` as their `START` and stage-2 reference (`0` extra keyframe credits), preventing character spawns, 180-degree side flips, and lighting jumps at cuts.
- **Deterministic cut-seam & tail-snap audit (`edit_video.py audit` & `assemble.py`)**: pure `ffmpeg + numpy` frame-delta scanner (`editkit.scan_clip_jumps`, `audit_segments`, `build_cut_sheet`) that detects 2-6 frame AI tail snaps (`recommended_trim_out`), internal jump cuts, solid-black opening frames (`dark_first_frame`), and per-cut boundary seam `MAE` (`frame_locked < 6`, `soft_match < 12`, `cut >= 12`), plus an annotated `(-1f, cut, +1f)` `--out-sheet` strip.
- **Ghost-free transition & Gate-4 Transition Board rules** across `SKILL.md`, `editing.md`, `review-rubric.md`, and `storyboard-schema.md` (prohibiting `xfade` cross-dissolves across head-scale/position shifts that cause two-head ghosting, and verifying speech tail clearance with `flow_transcribe` before trimming).

### Changed
- **Multi-character beat enforcement (`build_prompts.py`)**: `is_acting()` now matches compound beats like `"Sam and Lina"` via word boundaries and rejects characters whose `start` and `end` poses differ while omitted from `beats`, eliminating contradictory `"stays as in the first frame"` vs `last_frame` prompts.
- **Selective `--map` voice clamping (Pro `voice_convert.py` & `audio.md`)**: clamps merged VAD speech regions strictly to explicit `--map` speaker intervals so co-stars and silent gaps are never overwritten or degraded.

### Fixed
- **Pure-silence loudnorm guard (`editkit.py`, `assemble.py`)**: avoids invalid `measured_I=-inf` two-pass filter failures when assembling silent tracks.

## [1.4.0] - 2026-11-11

### Changed
- **Agensi delivery**: every script now ships as one self-contained file (`tools/build_agensi.py`, `tools/bundle_scoped.py`), because Agensi runs each script alone from a temporary file.
- `patch_flow_mcp.py` can use patch text embedded in the script when the `flow-mcp-patches` folder is not next to it.
- `cast_check.py` runs identity_check in the same process instead of starting a second file.
- `setup_env.py` checks the environment by re-running itself (`--probe`, `--selfcheck`) instead of `python -c`; no console window flashes on Windows.

## [1.2.0] - 2026-11-07

### Added
- **video-creator Autonomous Agent**: Added dedicated autonomous agent specification (agents/video-creator.md) for Google Antigravity and Claude Code, pre-configured with full flow MCP toolset and the deterministic 8-phase pipeline.
- **Antigravity UI Integration**: Updated install.ps1 and install.sh to package and register Flow Film Director as a native Antigravity plugin, enabling direct selection of video-creator from the UI Agents dropdown menu.
- **Claude Code Subagent Support**: Automated installation of video-creator.md into ~/.claude/agents/ for instant subagent invocation.
- **Production Showcases & Real-World Examples**:
  - Added **Example 1: Hassen's Story** (`hassen_story.mp4` with start reference `start_reference.jpg`) demonstrating single-character multi-environment continuity across 8 scenes in Tunisia and Italy.
  - Added **Example 2: Marwen & Hassen Action Remake** (`marwen_hassen_action.mp4` with dual character references `ref_hassen.jpg` and `ref_marwen.jpg`) demonstrating multi-character combat choreography without face-blending.
- **Comprehensive Directing Methodology**: Authored `examples/showcase/METHODOLOGY.md` explaining biometric auditing, zero-credit keyframing, contrastive lock design, audio ducking, and surgical post-production.

## [1.0.0] - 2026-11-06

### Added
- **Gated Directing Workflow**: Five-stage video direction system (Plan, Prepare, Keyframes, Shoot, Deliver) with automated quality gates and verification loops.
- **Character Likeness & Invariants**: Face identity auditing (YuNet + SFace), character lock texts, and prompt rules enforcing physical realism, natural motion, and face consistency across scenes.
- **Fast Mode (Direct R2V)**: Parallel Google Flow video generation directly from character reference images with human-paced request batching, grid-view enforcement, and builder-owned prompt generation under an 1800-character cap.
- **Precise Mode (Keyframe-to-Video)**: Two-stage zero-credit keyframe generation (Nano Banana start and end frames) with automated image selection before paid video rendering.
- **Audio & Soundtrack Engine**: Native timeline assembly, beat detection, automatic cut snapping to musical beat grids, audio ducking under dialogue, -14 LUFS loudness normalization, and voice conversion / speech generation with Resemble Perth provenance watermarking.
- **Post-Production & Surgical Editing**: Time-based range editing (trimming, slow motion, freeze frames, blur, title cards, logo overlays, audio muting/replacing) and single-period clip regeneration.
- **Reference Video Remaking**: Scene breakdown and MediaPipe pose tracking for reproducing staging, timing, and camera angles from reference footage.
- **Automated Validation Suite**: 19 offline end-to-end tests covering audio assembly, video editing, prompt rules, safety filters, and example storyboard compilation.
- **flow-mcp Integration**: Patch generator (`patch_flow_mcp.py`) supporting exact character attachment, parallel batch execution, and UI grid selection on GTAI-1/flow-mcp pinned to commit `84b548f`.
- **Installers**: Cross-platform setup scripts (`install.ps1` for Windows, `install.sh` for macOS/Linux) for Claude Code and Google Antigravity.
