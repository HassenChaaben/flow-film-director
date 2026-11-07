"""ElevenLabs Engine for Flow Film Director.

Provides:
- Instant Voice Cloning from character audio samples (e.g. WhatsApp .ogg, .mp3, .wav)
- Zero-shot Text-to-Speech across 30+ languages (including Tunisian Arabic, French, English)
- Speech-to-Speech voice conversion
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import requests

API_BASE = "https://api.elevenlabs.io/v1"


def get_api_key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY")


def check_auth() -> dict:
    key = get_api_key()
    if not key:
        return {"ok": False, "error": "ELEVENLABS_API_KEY environment variable not set"}
    try:
        r = requests.get(f"{API_BASE}/user", headers={"xi-api-key": key}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            sub = data.get("subscription", {})
            return {
                "ok": True,
                "tier": sub.get("tier", "unknown"),
                "character_count": sub.get("character_count", 0),
                "character_limit": sub.get("character_limit", 0),
                "can_clone": sub.get("can_use_instant_voice_cloning", False)
            }
        return {"ok": False, "error": f"API returned status {r.status_code}: {r.text}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def clone_voice(name: str, sample_paths: list[str | Path], description: str = "") -> dict:
    """Upload audio samples to ElevenLabs Voice Lab to create an instant cloned voice."""
    key = get_api_key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is required to clone a voice.")
    
    files = []
    opened = []
    try:
        for p in sample_paths:
            path = Path(p)
            if not path.exists():
                raise FileNotFoundError(f"Voice sample not found: {p}")
            
            # If Opus .ogg, convert to .wav or .mp3 so ElevenLabs API accepts it smoothly
            if path.suffix.lower() == ".ogg":
                wav_temp = path.with_suffix(".temp.wav")
                subprocess.run(["ffmpeg", "-y", "-i", str(path), "-ar", "44100", "-ac", "1", str(wav_temp)],
                               capture_output=True, check=True)
                f = open(wav_temp, "rb")
                opened.append((f, wav_temp))
                files.append(("files", (wav_temp.name, f, "audio/wav")))
            else:
                f = open(path, "rb")
                opened.append((f, None))
                files.append(("files", (path.name, f, "audio/mpeg" if path.suffix == ".mp3" else "audio/wav")))
        
        data = {
            "name": name,
            "description": description or f"Character voice clone for {name}",
            "labels": json.dumps({"source": "flow-film-director", "character": name})
        }
        
        r = requests.post(
            f"{API_BASE}/voices/add",
            headers={"xi-api-key": key},
            data=data,
            files=files,
            timeout=60
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs voice cloning failed ({r.status_code}): {r.text}")
        
        res = r.json()
        return {"ok": True, "voice_id": res.get("voice_id"), "name": name}
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
    voice_id: str,
    out_path: str | Path,
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.85
) -> Path:
    """Generate speech in the cloned voice using ElevenLabs Multilingual v2."""
    key = get_api_key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is required.")
    
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": 0.2,
            "use_speaker_boost": True
        }
    }
    
    r = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        headers=headers,
        json=payload,
        timeout=60
    )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs TTS failed ({r.status_code}): {r.text}")
    
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)
    return dst


def speech_to_speech(
    audio_path: str | Path,
    voice_id: str,
    out_path: str | Path,
    model_id: str = "eleven_multilingual_sts_v2"
) -> Path:
    """Convert an existing human voice performance into the target cloned voice."""
    key = get_api_key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is required.")
    
    src = Path(audio_path)
    with open(src, "rb") as f:
        files = {"audio": (src.name, f, "audio/mpeg" if src.suffix == ".mp3" else "audio/wav")}
        data = {
            "model_id": model_id,
            "voice_settings": json.dumps({
                "stability": 0.5,
                "similarity_boost": 0.85
            })
        }
        r = requests.post(
            f"{API_BASE}/speech-to-speech/{voice_id}",
            headers={"xi-api-key": key},
            data=data,
            files=files,
            timeout=90
        )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs STS failed ({r.status_code}): {r.text}")
    
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)
    return dst
