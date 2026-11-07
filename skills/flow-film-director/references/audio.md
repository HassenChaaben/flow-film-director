# Audio: character voices and soundtrack

Ask in Phase 1, every time (the answers go in `brief.md` and the `audio` block of storyboard.json):

1. **What should the viewer hear?** pick one mode
   - `native`: the clips' own sound (dialogue + ambience) - default for stories with dialogue
   - `soundtrack`: music over the whole film, nobody speaks - **ask for the soundtrack file path** (mp3/wav/m4a...),
     where in the song to start (seconds), and whether cuts should land on the beat
   - `voiceover`: a narrator over the pictures (a recorded file, or a character's cloned voice made with `speak`)
   - `mixed`: dialogue + music; the music dips automatically whenever someone speaks
2. **Who speaks, and with whose voice?** For every speaking character: Flow's stock voice is fine, or the user gives
   **voice samples** (voice notes, videos, recordings) and the character speaks with their real voice.
   Only voices of people who agreed (the user, friends who said yes). Never a public figure's voice.
3. Target loudness: -14 LUFS (social, YouTube - default) or -23 LUFS (broadcast).

## Character voices (VOICE venv: `VPY`, from `setup_voice_env.py`)

> [!IMPORTANT]
> **Default Voice Engine: Jamie Pine's Voicebox (`--engine voicebox` or Voicebox MCP)**  
> Whenever voice cloning, speech synthesis, or character dialogue is generated, **Voicebox is the default**. Voicebox is free and runs on this computer (the Voicebox desktop app, port 17493 on the loopback address) with Kokoro / Qwen3-TTS and Whisper STT. The other engines (`--engine local` for Chatterbox, `convert --engine rvc`) are local too: no voice audio ever leaves the machine.

1. **Profile** - once per character:
   `"%VPY%" voice_profile.py create --name Sam --samples <files or folders> --out film/<slug>/voices`
   Gate: `ok: true`. Flags to act on: TOO LITTLE SPEECH (< 8 s - ask for more), NOISY, CLIPPED, a second voice
   detected. 30-60 s of clean speech gives the closest voice; 10-15 s works.
   Save it WITH the character: `"cast": {"Sam": {..., "voice": "voices/Sam/profile.json"}}`.
   The profile suggests the stock Flow voice register to use when the character is created (`flow_voice_hint`; confirm
   the names with `flow_voices`). That stock voice only shapes timing and lip-sync - the real voice comes next.
2. **Generate** the dialogue scene normally (Veo 3.1 - Fast is best for speech). build_prompts.py asks Flow for clean
   close-microphone dialogue and no music, because clean speech converts best.
3. **Convert** each accepted dialogue clip:
   `"%VPY%" voice_convert.py clip --profile Sam=voices/Sam/profile.json --in clips/scene-04.mp4 --out clips/scene-04.voiced.mp4`
   Two speakers in one clip: `--profile Sam=... --profile Lina=... --map "0.0-2.3=Sam,2.6-5.0=Lina"` (times from
   `flow_transcribe`). Gate: `all_pass` (similarity to the profile >= its pass line), `max_length_change_ms` < 42 (one frame),
   duration unchanged. The picture is copied bit for bit, so lip-sync stays exactly as Flow made it.
   Put the result in `accepted.clip_voiced`; assembly uses it automatically.
4. **Check the words**: `flow_transcribe` the voiced clip and compare with the script; a changed word = redo the take.
5. **New lines without a picture** (narration, off-screen phone call, voice-over in the character's voice):
   `"%VPY%" voice_convert.py speak --profile voices/Sam/profile.json --text "..." --lang en --out vo/line-01.wav`
   Languages: en + ar da de el es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr zh. Same text + seed = same take.

Calibration (2026-11-04, real recordings): the same person's unseen speech 0.96; another person 0.69-0.73 (FAIL);
converted speech 0.86-0.90 (PASS); cloned new speech 0.88-0.90 (PASS). Pass line = profile consistency - 0.08, kept in
[0.78, 0.84]. Outputs carry Resemble's inaudible Perth watermark (marks them as AI-made).

## Soundtrack and final mix (skill venv: `PY`)

`"%PY%" assemble.py film/<slug>/storyboard.json` reads the `audio` block:
```json
"audio": {"mode": "soundtrack",
          "soundtrack": {"file": "music/track.mp3", "start": 12.0, "volume_db": 0, "fade_in": 0.5, "fade_out": 2.0,
                         "loop": true, "snap_cuts_to_beats": true, "max_shift": 0.5},
          "clip_volume": 0.0, "target_lufs": -14}
```
- soundtrack mode: clips muted (or quiet ambience with `clip_volume` 0.1-0.2); dialogue scenes are refused by the
  builder (use `mixed`). Music trimmed to the film, looped if shorter, faded, loudness-normalised (two-pass, limiter
  for punchy music, true peak <= -1.5 dBTP).
- beat-snapped cuts: tempo and beats are measured (60-180 BPM; ~6 ms accuracy on test tracks); each cut moves to the
  nearest beat within `max_shift`, only by shortening a shot or using frames the take still has; every shot keeps >= 1 s.
  The report lists every move. Ask for the BPM if the music has no clear beat (ambient, orchestral).
- mixed: music ducks ~20 dB under dialogue automatically (sidechain), comes back between lines.
- voiceover: `"voiceover": [{"file": "vo/line-01.wav", "at": 0.0}, {"file": "vo/line-02.wav", "at": 8.5}]`; clips at 25 %.
The film comes with `<film>.timeline.json` (needed for editing) and a loudness report. Check it by listening once:
`/watch-video` on the film, plus the numbers in the report.
