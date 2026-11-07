# Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| The agent has no `flow_*` tools | MCP server not registered or wrong path | Claude Code: `claude mcp list`; re-add with the absolute path to `flow-mcp/dist/index.js`. Antigravity: check `mcp_config.json` (double backslashes on Windows), restart |
| `dist/index.js` not found | flow-mcp not built | `npm install` then `npm run build` in the flow-mcp folder |
| `flow_status` says signed out | Google session expired | `npm run login` in the flow-mcp folder, sign in by hand, keep the window open |
| Jobs stall or time out | Display asleep, Chrome window minimised behind a lock screen | Keep the computer awake; in Antigravity use `timeoutSeconds: 600` |
| Stills skipped: "quoted more credits than max_credits" | Flow charges for x2-x4 image variants on some plans | Set `"variants": 1` or `2` in the scene and rebuild |
| `build_prompts.py` exit 1 | Storyboard error (model label, duration, missing file, banned word, text request) | Read `prompts/plan.md` -> "ERRORS", fix `storyboard.json`, rebuild |
| `model ... not found` from Flow | Model label not exact | Use exactly `Omni 1.1 Flash`, `Veo 3.1 - Lite`, `Veo 3.1 - Fast`, `Veo 3.1 - Quality` |
| `File not found` from flow-mcp | Relative path | All paths must be absolute (the builder does this; hand-made calls must too) |
| Face check says "not found" on a good still | Face too small or in profile | Use a closer framing; a deliberate profile may be WEAK if the visual check is clean |
| App bars / captions appear in generated scenes | Phone screenshots used as references | `prep_refs.py --crop-top/--crop-bottom`, use the `clean/` folder only |
| Object check passes on clearly different photos | Shared UI or watermark in the references | Clean the references first (same fix as above) |
| Pose score low although the clip looks right | Masked/costumed people, people cut by the frame | Check by eye with the side-by-side sheet; note it in the review |
| `ModuleNotFoundError: mediapipe` | Script run with the system Python | Use the skill's Python: `~/.flow-film/venv/Scripts/python.exe` (Windows) or `~/.flow-film/venv/bin/python` |
| Model download fails (face / pose models) | Network or proxy | Download the files listed in `facekit.py` / `motionkit.py` by hand into `~/.flow-film/models` |
| A paid clip disappeared from the queue | flow-mcp process restarted | Look at the Flow grid (`flow_assets`) before running it again - it may already exist |
| Skill not listed in Antigravity | Copied to the wrong folder | It must be `~/.gemini/config/skills/flow-film-director/SKILL.md`; restart Antigravity |
| Skill not listed in Claude Code | Wrong folder or YAML error | `~/.claude/skills/flow-film-director/SKILL.md`; restart Claude Code |
| Voicebox synthesis fails / offline | Voicebox app is closed | Launch the Voicebox desktop app from https://github.com/jamiepine/voicebox (runs on port 17493), or let `voice_convert.py` use the automatic local fallback |
