# Editing exact frames, scenes and periods of the film

The user says what to change in film time ("at 0:12 the hand looks wrong", "remove 0:20-0:23", "slow down the jump",
"put SALE -20% from 0:30 to 0:34"). Everything starts from the assembled film and its `<film>.timeline.json`.

## 1. Locate
`"%PY%" edit_video.py locate --timeline final/film.timeline.json --range 12 15`
-> which scene(s), which take, and the exact time inside the take (`take_from`/`take_to`, `scene_from`).
Grab the exact frame when a still matters: `edit_video.py frame --film final/film.mp4 --at 12.4 --out fix/f-12.4.png`.
Tell the user in one line what is there (scene, take, seconds) before changing anything.

## 2. Choose the kind of fix (cheapest that solves it)
| Problem in a period | Fix | Cost |
|---|---|---|
| Should not be there / too long | `cut` | free |
| Wrong pacing | `speed` (0.25-4x), `freeze` | free |
| Text, title, price, name, logo | `text` / `overlay` (never ask Flow for text) | free |
| Stray object, background person, plate | `blur` the box | free |
| Wrong framing (too wide) | `zoom` punch-in | free |
| Colour / brightness jump between shots | `color` on the period | free |
| Bad sound, wrong word, noise | `mute`, `volume`, `audio_replace` (with a `speak` line in the character's voice) | free |
| Title card / corrected still in between | `insert` image | free |
| Face, hands or action wrong in a period | regenerate ONLY that scene (Phase 5-6 retake with a corrected keyframe), then `splice` the same period from the new take | credits |
| Small local change on a good clip (object colour, light) | `flow_edit` on that take, then `splice` | ~20 credits, ask |
| One bad frame (glitch) | `frame` -> fix the still (free image with the same references) -> `insert` it for 1-2 frames over a `cut` of the bad frames, or `freeze` the good neighbour frame | free |

Regenerating a period: change ONE field of that scene in storyboard.json, `build_prompts.py --only <id>`, make the new
keyframe/take, review it with the usual gates (identity / object / motion), then splice:
`{"op": "splice", "range": [12.0, 15.0], "source": "clips/scene-04-take3.mp4"}` - the take time is found from the
timeline, so the new take must keep the same timing (motion_match on the new take tells you; otherwise use
`replace` with an explicit `source_in`). Use `"audio": "original"` to keep the existing dialogue/music under the
new picture.

## 3. Apply (one file, in order; times refer to the film after the previous edit)
```json
{"edits": [
  {"op": "cut", "range": [20.0, 23.0]},
  {"op": "splice", "range": [12.0, 15.0], "source": "clips/scene-04-take3.mp4", "audio": "original"},
  {"op": "text", "range": [30.0, 34.0], "text": "SALE -20%", "position": "bottom", "size": 0.07},
  {"op": "fade", "in": 0.5, "out": 1.0}
]}
```
`"%PY%" edit_video.py apply --timeline final/film.timeline.json --edits edits/v2.json --out final/film-v2.mp4`
Writes the new film and `film-v2.timeline.json` (edit again from there). Keep every version: `film-vN.mp4`.

## 4. Check the edit
- the report: duration before/after each step (cuts and inserts change it by exactly their length);
- identity_check / object_check on the changed period of the new film (`--every 0.25`);
- look at the frames around each boundary (`contact_sheet.py --video final/film-v2.mp4 --at ...`) and listen across it;
- edits change only their range: tested - inside the range the picture changes strongly, outside it stays identical,
  joins are frame-accurate, sound stays in sync (tests/run_tests.py).
