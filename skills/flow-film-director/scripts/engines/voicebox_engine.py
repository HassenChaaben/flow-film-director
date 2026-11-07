"""Voicebox Engine for Flow Film Director.

Talks to Jamie Pine's Voicebox (the free, open-source "voicebox" desktop app by jamiepine on GitHub) running on
THIS computer:
- zero-shot voice cloning from audio samples, local text-to-speech (Kokoro, Qwen3-TTS, Chatterbox), Whisper STT
- REST API on the loopback address only. The host is fixed to 127.0.0.1 (only the port can change, through
  ~/.flow-film/voicebox.json {"port": 17493}), so audio never leaves the machine.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import requests

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 17493
CONFIG = Path.home() / ".flow-film" / "voicebox.json"
# trust_env=False: never route loopback traffic through a system HTTP proxy, so audio stays on this computer.
HTTP = requests.Session()
HTTP.trust_env = False


def get_port() -> int:
    try:
        port = int(json.loads(CONFIG.read_text(encoding="utf-8")).get("port", DEFAULT_PORT))
    except (OSError, ValueError, AttributeError):
        port = DEFAULT_PORT
    if not 1 <= port <= 65535:
        raise ValueError(f"bad Voicebox port {port} in {CONFIG}")
    return port


def set_port(port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError(f"bad Voicebox port {port}")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"port": port}), encoding="utf-8")


def get_base_url() -> str:
    return f"http://{LOOPBACK}:{get_port()}"


def check_voicebox_ready() -> dict:
    """Check if the local Voicebox application/daemon is running and responsive."""
    base_url = get_base_url()
    try:
        # Check /profiles or /health or root
        r = HTTP.get(f"{base_url}/profiles", timeout=3)
        if r.status_code == 200:
            profiles = r.json() if isinstance(r.json(), list) else r.json().get("profiles", [])
            return {
                "ok": True,
                "url": base_url,
                "profile_count": len(profiles),
                "profiles": profiles
            }
        return {"ok": False, "error": f"Voicebox returned status {r.status_code} at {base_url}"}
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "error": f"Voicebox not running at {base_url}. Start the Voicebox desktop app on this computer."
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_profiles() -> list[dict]:
    """Retrieve available voice profiles from the local Voicebox app."""
    base_url = get_base_url()
    try:
        r = HTTP.get(f"{base_url}/profiles", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("profiles", [])
    except Exception:
        pass
    return []


def clone_voice(name: str, sample_paths: list[str | Path], description: str = "") -> dict:
    """Create or register a cloned voice profile in Voicebox from local audio samples."""
    base_url = get_base_url()
    check = check_voicebox_ready()
    if not check["ok"]:
        raise RuntimeError(f"Cannot clone voice in Voicebox: {check['error']}")

    files = []
    opened = []
    try:
        for p in sample_paths:
            path = Path(p)
            if not path.exists():
                raise FileNotFoundError(f"Voice sample not found: {p}")
            
            # If Opus .ogg, convert to 24kHz/44.1kHz .wav for compatibility
            if path.suffix.lower() == ".ogg":
                wav_temp = path.with_suffix(".vb_temp.wav")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(path), "-ar", "24000", "-ac", "1", str(wav_temp)],
                    capture_output=True, check=True
                )
                f = open(wav_temp, "rb")
                opened.append((f, wav_temp))
                files.append(("audio_files", (wav_temp.name, f, "audio/wav")))
            else:
                f = open(path, "rb")
                opened.append((f, None))
                files.append(("audio_files", (path.name, f, "audio/wav" if path.suffix == ".wav" else "audio/mpeg")))

        data = {
            "name": name,
            "description": description or f"Flow Film Director clone for {name}"
        }

        # Try POST /profiles endpoint
        r = HTTP.post(f"{base_url}/profiles", data=data, files=files, timeout=60)
        if r.status_code in [200, 201]:
            res = r.json()
            profile_id = res.get("id") or res.get("profile_id") or name
            return {"ok": True, "profile_id": profile_id, "name": name}
        else:
            raise RuntimeError(f"Voicebox voice cloning failed ({r.status_code}): {r.text}")
    finally:
        for f, tmp in opened:
            f.close()
            if tmp and Path(tmp).exists():
                try:
                    Path(tmp).unlink()
                except Exception:
                    pass


def speak(
    text: str,
    profile_id_or_name: str,
    out_path: str | Path,
    engine: str = "kokoro"
) -> Path:
    """Synthesize speech using Voicebox's local multi-engine TTS (POST /generate)."""
    base_url = get_base_url()
    check = check_voicebox_ready()
    if not check["ok"]:
        raise RuntimeError(f"Voicebox synthesis failed: {check['error']}")

    payload = {
        "text": text,
        "profile_id": profile_id_or_name,
        "profile": profile_id_or_name,
        "engine": engine
    }

    # Voicebox exposes /generate for rendering audio files
    r = HTTP.post(
        f"{base_url}/generate",
        json=payload,
        timeout=90
    )
    if r.status_code != 200:
        # Fallback retry to /speak or query parameters if schema differs
        r = HTTP.post(
            f"{base_url}/speak",
            json=payload,
            timeout=90
        )
        if r.status_code != 200:
            raise RuntimeError(f"Voicebox TTS generation failed ({r.status_code}): {r.text}")

    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)
    return dst


def transcribe(audio_path: str | Path, model: str = "turbo") -> str:
    """Transcribe an audio file using Voicebox's local Whisper STT engine."""
    base_url = get_base_url()
    check = check_voicebox_ready()
    if not check["ok"]:
        raise RuntimeError(f"Voicebox transcribe failed: {check['error']}")

    src = Path(audio_path)
    with open(src, "rb") as f:
        files = {"audio": (src.name, f, "audio/wav")}
        r = HTTP.post(f"{base_url}/transcribe", files=files, data={"model": model}, timeout=60)
        if r.status_code == 200:
            res = r.json()
            return res.get("text", "")
        raise RuntimeError(f"Voicebox transcription failed ({r.status_code}): {r.text}")
