---
name: edit-voice
description: Replace or convert voices in video scenes with a character's real cloned voice, preserving exact words, phrase timing, lip-sync, and clean background music with sidechain ducking.
---

# Voice Editing & Voice Conversion Skill (`edit-voice`)

Performs speech-to-speech voice conversion on video files: keeps the original spoken words, cadence, and timing, but replaces the voice timbre with the character's real voice profile.

> [!IMPORTANT]
> **Default Voice Engine: Jamie Pine's Voicebox (`--engine voicebox` or Voicebox MCP)**  
> When performing voice cloning or speech synthesis, Voicebox is the default. Voicebox is 100% free, runs on this computer (port 17493, loopback only), and requires no API keys.

## Common Pitfalls & Why Naive Conversion Fails

1. **Background Music Contamination**:
   If a video already has background music mixed in, passing that audio directly into voice conversion corrupts the output. Speech-to-speech AI models (PerthNet / Chatterbox) expect clean vocal input. When fed instruments or drums, they hallucinate robotic artifacts.
2. **VAD Micro-Fragmentation**:
   Simple RMS-based Voice Activity Detectors (VAD) cut continuous Arabic or conversational sentences into dozens of 0.2–0.4 second micro-chops during natural pauses between words. Short chops lose speaker context and sound robotic.
3. **Crossfade Phase Distortion**:
   Splice crossfades across background music create audible wobbles, phasing, and clicks.

## Deterministic Dual-Path Architecture

### Path A: Production Line / Stem Replacement (Highest Quality)
When the project has isolated dialogue lines (from TTS or studio recording) and a soundtrack file:
1. Convert each clean line independently with the target voice profile:
   ```bash
   "%VPY%" voice_convert.py line --profile "<profile.json>" --in "vo/line-01.wav" --out "vo_cloned/line-01.wav"
   ```
2. Verify speaker cosine similarity $\ge 0.78$ and duration drift $< 42\text{ ms}$.
3. Mix the converted lines into the video at their exact timeline offsets, applying sidechain compression ducking to the soundtrack (`-12 dB` attenuation during speech, `50 ms` attack, `300 ms` release).
4. Mux directly with video stream using `-c:v copy`.

### Path B: In-Video Voice Conversion (For Standalone Mixed Videos)
When given a pre-rendered `.mp4` video with existing audio:
1. **Phrase-Level Boundary Extraction**:
   Use Whisper word timestamps (`flow_transcribe` or SRT subtitle timestamps) rather than raw energy VAD. This guarantees that entire sentences (e.g. 4–7 seconds) are converted as single continuous units.
2. **Vocal Stem Conversion**:
   Run voice conversion on the vocal regions using the character's 24 kHz reference profile.
3. **Loudness & Dynamics Matching**:
   Match loudness to `-20 LUFS` with soft knee limiting.
4. **Clean Recombination**:
   Re-integrate with smooth crossfades (`25 ms`), ensuring zero clipping (`peak <= 0.99`).

## Verification & Quality Gates
- **Speaker Similarity Gate**: Cosine similarity between converted speech and target profile $\ge 0.78$.
- **Timing Gate**: $\Delta t \le 42\text{ ms}$ per line to maintain frame-accurate lip-sync.
- **Audio Cleanliness**: Zero clipping, clean ducking transitions under dialogue.
