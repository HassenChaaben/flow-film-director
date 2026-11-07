# Optional: VideoDB (cloud video search, indexing, transcripts, dubbing)

VideoDB is a CLOUD service (a third-party product, not part of this skill). Everything it analyses must be uploaded to its servers.
Use it only when it is connected AND the user agreed, in this session, to upload that specific video. The skill's
own pipeline never depends on it: every gate works locally without it.

## When it adds value
| Need | VideoDB feature | Local alternative already in the skill |
|---|---|---|
| Find a moment by description in a long reference video ("where does he raise both hands?") | scene index + semantic search | ref_video_breakdown.py (measured events) + reading frames |
| Check a generated take semantically ("does the man put on the mask?") | index + search on the take | motion_match.py + realism review |
| Word-timed transcript of a reference or take | spoken-word index / transcripts | flow_transcribe (whisper.cpp) |
| Foreign-language version of the finished film | dubbing | voice_convert.py speak (character's own voice) + assemble voiceover |
| Subtitles as a hosted stream | add_subtitle | flow_captions (burned in, local) |
Do NOT use it to assemble, trim or generate - the local pipeline does that with exact control (and keeps the files local).

## Setup (the user does it; it is their account)
This skill ships no VideoDB code and no VideoDB address. If the user wants it, they install VideoDB's own
plugin in Claude Code themselves (`/plugin marketplace add video-db/skills`, then `/plugin install videodb@videodb-skills`
and `/videodb:setup`) and log in with their own account. Pricing and limits: VideoDB's own console.

## Rules
- Ask before every upload: name the file, say it goes to VideoDB's cloud. Never upload the user's photos or private
  footage without a yes in this session.
- Results come back mostly as stream URLs; download what you need and keep the local files as the source of truth.
- Use its timestamps as hints, then confirm them on the local timeline (`edit_video.py locate`, frames).
