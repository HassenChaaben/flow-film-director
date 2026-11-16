"""Tests for bridge-locked continuity prompts, frame-delta jump detection, and cut-seam audits."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "flow-film-director" / "scripts"
PRO_SCRIPTS = ROOT.parent / "flow-film-director-pro" / "scripts"
PY = sys.executable


def _make_video_from_rgb(path: Path, frames_rgb: np.ndarray, fps: int = 24) -> Path:
    """Encode an (N, H, W, 3) uint8 RGB array into an H.264 MP4 with silent stereo audio."""
    n, h, w, _ = frames_rgb.shape
    dur = n / fps
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{w}x{h}", "-framerate", str(fps), "-i", "-",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={dur:.4f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    proc = subprocess.run(cmd, input=frames_rgb.astype(np.uint8).tobytes(), capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return path


def _smooth_clip(n_frames: int, color_start, color_end, h: int = 90, w: int = 160) -> np.ndarray:
    """Create n_frames smoothly interpolating from color_start to color_end."""
    c0 = np.array(color_start, dtype=np.float32)
    c1 = np.array(color_end, dtype=np.float32)
    frames = np.zeros((n_frames, h, w, 3), dtype=np.uint8)
    for i in range(n_frames):
        alpha = i / max(1, n_frames - 1)
        frames[i] = np.clip((1.0 - alpha) * c0 + alpha * c1, 0, 255).astype(np.uint8)
    return frames


def _run_script(script: str, args: list[str], ok_codes=(0,)) -> tuple[int, dict]:
    p = subprocess.run(
        [PY, str(SCRIPTS / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert p.returncode in ok_codes, f"{script} failed ({p.returncode}):\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}"
    out = p.stdout.strip()
    start = out.find("{")
    return p.returncode, json.loads(out[start:]) if start >= 0 else {"raw": out}


def _base_storyboard(base: Path) -> dict:
    for name in ("s1-start.png", "s1-end.png", "s2-end.png"):
        (base / "keyframes").mkdir(parents=True, exist_ok=True)
        (base / "keyframes" / name).write_bytes(b"png-stub")
    return {
        "flow_project": "BridgeDemo",
        "intent": "story",
        "default_model": "Omni 1.1 Flash",
        "skip_look_check": True,
        "cast": {
            "Sam": {"kind": "person", "ref": "asset:Sam", "lock": "Sam: 30yo, dark eyes, no glasses."},
            "Lina": {"kind": "person", "ref": "asset:Lina", "lock": "Lina: 28yo, dark coat, brown hair."},
        },
        "scenes": [
            {
                "id": 1,
                "duration": 4,
                "characters": [{"name": "Sam", "start": "stands at doorway", "end": "steps inside"}],
                "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "steps inside"}],
                "use_end_frame": True,
                "accepted": {"start": "keyframes/s1-start.png", "end": "keyframes/s1-end.png"},
            },
            {
                "id": 2,
                "duration": 4,
                "bridge_from_prev": True,
                "characters": [
                    {"name": "Sam", "start": "having just stepped inside", "end": "turns to look ahead"},
                ],
                "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "turns to look ahead"}],
                "use_end_frame": True,
            },
        ],
    }


def test_bridge_from_prev_chains_end_to_next_start_and_waits(tmp_path):
    sb = _base_storyboard(tmp_path)
    sb_path = tmp_path / "storyboard.json"
    sb_path.write_text(json.dumps(sb), encoding="utf-8")

    # Stage 2 for scene 2 should build using scene 1's accepted.end without creating any stage1 START job
    code, res = _run_script("build_prompts.py", [str(sb_path)])
    assert code == 0 and res["stage1"] == 0 and res["stage2"] == 1
    s2 = json.loads((tmp_path / "prompts" / "stage2-end-keyframes.json").read_text(encoding="utf-8"))["scenes"][0]
    expected_s1_end = str((tmp_path / "keyframes" / "s1-end.png").resolve())
    assert expected_s1_end in s2["reference_images"]

    # Once scene 2 END is accepted, stage 3 for scene 2 automatically uses s1-end as first_frame
    sb["scenes"][1]["accepted"] = {"end": "keyframes/s2-end.png"}
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    code, res = _run_script("build_prompts.py", [str(sb_path), "--only", "2"])
    assert code == 0 and res["stage3"] == 1
    s3 = json.loads((tmp_path / "prompts" / "stage3-video.json").read_text(encoding="utf-8"))["scenes"][0]
    assert s3["first_frame"] == expected_s1_end
    assert s3["last_frame"] == str((tmp_path / "keyframes" / "s2-end.png").resolve())

    # If scene 1 has no accepted.end yet, bridged scene 2 waits instead of building a mismatched stage 1 START
    del sb["scenes"][0]["accepted"]["end"]
    del sb["scenes"][1]["accepted"]
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    code, res = _run_script("build_prompts.py", [str(sb_path)])
    assert code == 0 and res["stage1"] == 0 and res["stage2"] == 1  # only scene 1 END is queued; scene 2 waits
    assert any("bridged from scene 01 END" in w for w in res["waiting"])

    # Scene 1 cannot set bridge_from_prev=true
    sb["scenes"][0]["bridge_from_prev"] = True
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    code, res = _run_script("build_prompts.py", [str(sb_path)], ok_codes=(1,))
    assert code == 1 and any("bridge_from_prev" in e for e in res["errors"])

    # Scene 2 bridge_from_prev=true must fail fast when scene 1 has use_end_frame=false and no accepted.end
    sb["scenes"][0]["bridge_from_prev"] = False
    sb["scenes"][0]["use_end_frame"] = False
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    code, res = _run_script("build_prompts.py", [str(sb_path)], ok_codes=(1,))
    assert code == 1 and any("use_end_frame" in e for e in res["errors"])


def test_multichar_pose_change_without_beat_is_refused_and_combo_who_works(tmp_path):
    sb = _base_storyboard(tmp_path)
    # Scene with Lina changing start -> end and omitted from beats must be refused ALREADY in Phase 4 (before accepted keyframes)
    sb["scenes"] = [
        {
            "id": 1,
            "duration": 4,
            "characters": [
                {"name": "Sam", "start": "stands in foreground", "end": "turns left"},
                {"name": "Lina", "start": "crouching in corner", "end": "retreating into doorway"},
            ],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "turns left slowly"}],
            "use_end_frame": True,
        }
    ]
    sb_path = tmp_path / "storyboard.json"
    sb_path.write_text(json.dumps(sb), encoding="utf-8")

    code, res = _run_script("build_prompts.py", [str(sb_path)], ok_codes=(1,))
    assert code == 1 and any("Lina" in e and "beats" in e for e in res["errors"])

    # Also verify case-insensitive compound beat "sam and lina" marks BOTH as acting
    sb["scenes"][0]["accepted"] = {"start": "keyframes/s1-start.png", "end": "keyframes/s1-end.png"}
    sb["scenes"][0]["beats"] = [{"from": 0, "to": 4, "who": "sam and lina", "action": "step apart cleanly"}]
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    code, res = _run_script("build_prompts.py", [str(sb_path)])
    assert code == 0
    prompt = json.loads((tmp_path / "prompts" / "stage3-video.json").read_text(encoding="utf-8"))["scenes"][0]["prompt"]
    assert "Sam stays as in the first frame" not in prompt
    assert "Lina stays as in the first frame" not in prompt


def test_editkit_and_edit_video_audit_detect_tail_snap_seams_and_dark_frame0(tmp_path):
    # Clip 1: 48 frames shifting warm grey -> mid teal cleanly (no internal jump)
    c1 = _smooth_clip(48, (90, 90, 90), (60, 140, 140))
    p1 = _make_video_from_rgb(tmp_path / "c1.mp4", c1)

    # Clip 2: starts EXACTLY on (60, 140, 140) -> frame-locked seam with c1, BUT snaps last 3 frames to bright magenta!
    c2_body = _smooth_clip(45, (60, 140, 140), (70, 150, 155))
    c2_snap = _smooth_clip(3, (250, 20, 220), (255, 25, 225))
    p2 = _make_video_from_rgb(tmp_path / "c2.mp4", np.concatenate([c2_body, c2_snap], axis=0))

    # Clip 3: hard visual change (dark emerald) -> intentional cut from c2, plus test black first frame on c_black
    c3 = _smooth_clip(48, (20, 40, 25), (30, 60, 35))
    p3 = _make_video_from_rgb(tmp_path / "c3.mp4", c3)
    c_black = np.concatenate([_smooth_clip(3, (0, 0, 0), (1, 1, 1)), _smooth_clip(45, (80, 90, 100), (90, 100, 110))], axis=0)
    p_black = _make_video_from_rgb(tmp_path / "c_black.mp4", c_black)

    # 1. audit --clip detects the tail snap on c2 and gives recommended_trim_out before the snap (~45/24 = 1.875s)
    code, clip_rep = _run_script("edit_video.py", ["audit", "--clip", str(p2)])
    assert code == 0
    assert len(clip_rep["tail_jumps"]) >= 1
    assert clip_rep["recommended_trim_out"] is not None
    assert 1.75 <= clip_rep["recommended_trim_out"] <= 1.92

    # 2. assemble two bridged scenes + one cut scene, triggering seam classification & bridge_mismatch warning
    sb = {
        "flow_project": "AuditDemo",
        "audio": {"mode": "native"},
        "scenes": [
            {"id": 1, "accepted": {"clip": str(p1)}},
            {"id": 2, "bridge_from_prev": True, "accepted": {"clip": str(p2)}, "trim": [0.0, 1.875]},
            {"id": 3, "bridge_from_prev": True, "accepted": {"clip": str(p3)}},  # intentional bad bridge match to test mismatch flag
        ],
    }
    sb_path = tmp_path / "sb.json"
    sb_path.write_text(json.dumps(sb), encoding="utf-8")
    out_film = tmp_path / "final" / "film.mp4"
    code, asm = _run_script("assemble.py", [str(sb_path), "--out", str(out_film)])
    assert code == 0
    assert len(asm["transitions"]) == 2
    assert asm["transitions"][0]["kind"] == "frame_locked" and asm["transitions"][0]["seam_mae"] < 6.0
    assert asm["transitions"][1]["bridge_mismatch"] is True and asm["transitions"][1]["seam_mae"] >= 12.0

    # 3. audit --timeline preserves bridged/bridge_mismatch metadata, writes sheet, and handles dark frame 0 + post-edit freeze/image/None bounds
    sheet = tmp_path / "review" / "cuts-audit.jpg"
    code, tl_rep = _run_script(
        "edit_video.py",
        ["audit", "--timeline", asm["timeline"], "--out-sheet", str(sheet)],
    )
    assert code == 0
    assert sheet.exists() and sheet.stat().st_size > 1000
    assert tl_rep["transitions"][0]["kind"] == "frame_locked" and tl_rep["transitions"][0]["bridged"] is True
    assert tl_rep["transitions"][1]["kind"] == "cut" and tl_rep["transitions"][1]["bridge_mismatch"] is True

    # Post-edit timeline edge case: freeze (0-frame clip_in==clip_out), still image PNG insert (raw bytes), and None clip_out
    img_path = tmp_path / "card.png"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1",
         "-frames:v", "1", str(img_path)],
        check=True,
    )
    mixed_tl = tmp_path / "mixed.timeline.json"
    mixed_tl.write_text(json.dumps({
        "film": str(out_film),
        "segments": [
            {"scene": 1, "clip": str(p1), "clip_in": 0.0, "clip_out": None, "film_start": 0.0, "film_end": 2.0, "speed": 1.0},
            {"scene": "freeze", "clip": str(p1), "clip_in": 1.0, "clip_out": 1.0, "film_start": 2.0, "film_end": 3.5, "speed": 0.0, "kind": "freeze"},
            {"scene": "insert", "clip": str(img_path), "clip_in": 0.0, "clip_out": 2.0, "film_start": 3.5, "film_end": 5.5, "speed": 1.0, "kind": "image"},
        ],
    }), encoding="utf-8")
    mixed_sheet = tmp_path / "review" / "mixed-sheet.jpg"
    code, mixed_rep = _run_script("edit_video.py", ["audit", "--timeline", str(mixed_tl), "--out-sheet", str(mixed_sheet)])
    assert code == 0 and mixed_sheet.exists() and len(mixed_rep["transitions"]) == 1

    code, blk_rep = _run_script("edit_video.py", ["audit", "--clip", str(p_black)])
    assert code == 0 and blk_rep["dark_first_frame"] is True


@pytest.mark.skipif(not (PRO_SCRIPTS / "voice_convert.py").exists(), reason="Pro overlay not present")
def test_voice_convert_map_clamps_merged_region(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.syspath_prepend(str(PRO_SCRIPTS))
    spec = importlib.util.spec_from_file_location("voice_convert_pro", PRO_SCRIPTS / "voice_convert.py")
    vc_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc_mod)
    assert vc_mod.select_work_spans(
        merged=[(0.02, 5.10)],
        mapping=[(0.0, 1.95, "Bilal")],
        default_name="Bilal",
    ) == [(0.02, 1.95, "Bilal")]
    assert vc_mod.select_work_spans(
        merged=[(0.1, 4.5)],
        mapping=None,
        default_name="Sam",
    ) == [(0.1, 4.5, "Sam")]
    assert vc_mod.select_work_spans(
        merged=[(0.1, 4.5)],
        mapping=[(0.2, 1.8, "Sam"), (2.2, 4.1, "Lina"), (4.45, 4.50, "Tinyskip")],
        default_name="Sam",
    ) == [(0.2, 1.8, "Sam"), (2.2, 4.1, "Lina")]
    assert vc_mod.select_work_spans(
        merged=[(0.1, 1.0)],
        mapping=[(2.0, 3.0, "Bilal")],
        default_name="Bilal",
    ) == []
