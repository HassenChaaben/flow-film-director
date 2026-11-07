# Optional: VideoDB (cloud video search, indexing, transcripts, dubbing)

VideoDB (videodb.io, github.com/video-db) is a CLOUD service. Everything it analyses must be uploaded to its servers.
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

## Setup (the user does the login; it is their account)
Claude Code:
```
/plugin marketplace add video-db/skills
/plugin install videodb@videodb-skills
/videodb:setup                      # installs the Python SDK, asks for VIDEO_DB_API_KEY (console.videodb.io)
```
or only the hosted MCP server: `claude mcp add --transport http videodb https://mcp.videodb.io/mcp`, then `/mcp` to log in.
Antigravity (not documented by VideoDB - try in this order): in `%USERPROFILE%\.gemini\config\mcp_config.json`
`"videodb": {"serverUrl": "https://mcp.videodb.io/mcp"}`; if the login does not work there, the local server:
`"videodb": {"command": "uvx", "args": ["videodb-director-mcp", "--api-key", "<VIDEO_DB_API_KEY>"]}`.
Free tier: about $20 of credits, no card (2026-11). Pricing and limits beyond that: check console.videodb.io.

## Rules
- Ask before every upload: name the file, say it goes to VideoDB's cloud. Never upload the user's photos or private
  footage without a yes in this session.
- Results come back mostly as stream URLs; download what you need and keep the local files as the source of truth.
- Use its timestamps as hints, then confirm them on the local timeline (`edit_video.py locate`, frames).
