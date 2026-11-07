---
name: voice-cloning
description: Create biometric voice profiles from voice notes (WhatsApp, audio clips, voice memos) and generate character speech matching exact timbre, pitch, and accent using Jamie Pine's Voicebox (default) or local Chatterbox / RVC - all on this computer.
---

# Voice Cloning Skill (`voice-cloning`)

Extracts, cleans, and builds persistent character voice profiles from raw audio recordings (WhatsApp voice messages, microphone recordings, film takes). Provides character-locked speech generation and embedding verification.

> [!IMPORTANT]
> **Default Engine: Jamie Pine's Voicebox (`--engine voicebox` or Voicebox MCP)**  
> Whenever voice cloning or speech generation is required, always use Voicebox. Voicebox is 100% free, runs on this computer (port 17493, loopback only), and requires no API keys. Every engine is local: no voice audio leaves the machine.

## When to Use
- User provides a character's voice note (e.g. WhatsApp `.ogg`, `.mp3`, `.wav`, `.m4a`).
- User asks to clone a voice, create a voice profile, or generate dialogue in a real person's voice.
- Pre-requisite for `edit-voice` (voice replacement in video).

## Environment
Runs using the dedicated voice venv:
- Windows: `%USERPROFILE%\.flow-film\voice-venv\Scripts\python.exe`
- Linux/Mac: `~/.flow-film/voice-venv/bin/python`

If not set up, run:
```bash
python scripts/setup_voice_env.py
```

## Step-by-Step Workflow

### 1. Ingest & Audit Voice Sample
Clean raw audio (denoise, remove rumble, normalize to -20 LUFS):
```bash
"%VPY%" voice_profile.py create --name <CharacterName> --samples "<path/to/voice_sample.ogg>" --out "film/<slug>/voices"
```
The tool:
- Converts any format (`.ogg`, `.mp3`, `.m4a`, `.wav`) to 24 kHz mono.
- Removes frequencies below 70 Hz (low rumble).
- Calculates Signal-to-Noise Ratio (SNR), clipping percentage, and median fundamental frequency ($F_0$ pitch).
- Generates 256-dimensional speaker embedding (`embedding.npy`) and clean reference audio (`reference.wav`).

### 2. Quality Gates
Check `profile.json`:
- `speech_seconds`: minimum 8.0 s (15–60 s recommended for closest likeness).
- `consistency`: $\ge 0.80$ (speaker does not switch voices or include background chatter).
- `pass_line`: threshold for verification (typically $0.78$).

### 3. Generate Speech in Character's Voice
```bash
# Default: Voicebox (100% free, local AI voice studio)
"%VPY%" voice_convert.py speak --engine voicebox --profile "film/<slug>/voices/<CharacterName>/profile.json" --text "<Speech text>" --lang <lang_code> --out "film/<slug>/vo/line-01.wav"

```
- Supported languages: `ar` (Arabic & dialects), `en` (English), `fr`, `it`, `es`, `de`, `zh`, `ja`, etc.
- Seed parameter (`--seed <int>`) guarantees reproducible takes.
- Output is verified with cosine similarity against the profile embedding.
