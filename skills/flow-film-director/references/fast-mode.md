# Fast mode (default): a finished video in minutes, not hours

`"mode": "fast"` in storyboard.json. One parallel round of videos made straight from the Flow characters
(Ingredients), with a prompt the builder owns completely, then a measured review and one retake round.
`"mode": "precise"` keeps the full gated pipeline (verified keyframes per scene) for remakes and hero shots.

## Measured live (2026-11-05, Omni 1.1 Flash 720p, flow-mcp with the skill's patch)
- 5 single-character clips: 5.8 min wall time, 35 credits; face scores 0.60-0.69 mean (4 PASS, 1 WEAK).
- 3 two-person fight clips: 5.3 min. Clip 2 right (each fights a guard); clip 1 WRONG staging (guards behind
  -> heroes faced each other) -> now refused by the builder; clip 3 refused by Flow ("unusual activity",
  submits were 2.5 s apart) -> submits are now 20-40 s apart.
- Rerun after the fixes (2026-11-06): fight staging right in all 3 clips (guards in front, every blow at a guard),
  outfits kept, Flow accepted every prompt. 3 clips 5-6 min per parallel batch, 10 credits each (720p 6 s).
  Faces (identity_check, 0.50 line): the calm medium final scene measured 0.56 / 0.52 for the two people (WEAK, above
  0.50); the wide moving fight scenes measured 0.36-0.46 (WEAK / FAIL) even where the person looks right by eye.
  An independent review rated the result "partly meets" the goal: right story, faces below the line in wide action.
  Fixes since: one clear three-quarter face moment at the start of every fight scene, and fast_review.py retakes
  every scene under 0.50 once, automatically.
- Edit test: one beat changed in scene 3 -> `build_prompts.py --only 3` -> `run_stage.mjs --only 3` (2.5 min,
  10 credits) -> reassembled; scenes 1-2 frame-identical, only scene 3 changed, change visible as asked.
- Where the time goes: filling the composer (attaching 1-2 characters, settings) takes ~60 s per scene; a
  render takes 2-3 min and overlaps with the next submits. Realistic: about 1.5 min per scene, so ~6-8 scenes
  in ~10-12 min, a 60 s film (8 x 8 s) in ~12-15 min. Do not promise less than you measured.

## Steps
1. Brief (one round of questions): idea or reference video, characters, tone, audio. Write storyboard.json with
   `"mode": "fast"`, a `tone`, and per character `identity` (one sentence of measured features) and `outfit`.
2. Characters exist in the open Flow project (`flow_characters`) AND their saved portraits pass `cast_check.py`
   (one face, PASS, face >= 0.18 of the picture height); otherwise create them from cast_check's `best` photo (Phase 2-3 of SKILL.md, verification stills can be skipped when the audit is clean).
3. `build_prompts.py storyboard.json` -> `prompts/stage-fast-video.json` (every scene: Ingredients refs, `builder_lock`,
   `parallel`). Show the expected credits once; on OK send it as ONE `flow_generate` call (or
   `node scripts/run_stage.mjs prompts/stage-fast-video.json --flow-mcp <dir>`).
4. Review: `fast_review.py --run prompts/last-run.json --storyboard storyboard.json --gallery bible/gallery.json`
   (run_stage.mjs writes last-run.json). It keeps a scene only when every main character's mean face score is
   >= 0.50 and none FAIL. Then the contact sheet / `/watch-video` and the clip checklist for the action. Fights:
   allies side by side or back to back, every blow at an opponent, never at each other, the asked number of opponents.
5. Retake round (automatic, once): face failures -> retake as is (or tighten framing to medium); action failures ->
   change ONE storyboard field (staging, framing, action, duration). `build_prompts.py --only <ids>`,
   `run_stage.mjs --only <ids>` (ids = storyboard scene ids). Still failing after one retake: keep the better take,
   tell the user which scene and why. Then `assemble.py`.
6. Edits afterwards: Phase 8 (edit_video.py locate/apply, or regenerate one scene and splice).

## Prompt rules the builder applies (Google Veo guide + live tests)
- Order: tone -> shot -> who (main characters + opponents) -> sides -> start states -> timed play-by-play with
  targets -> place, light -> camera -> outfit + identity per character -> audio -> realism sentence -> short Avoid list.
- Tone stated every time (Google's own examples are comedic; an unstated tone drifts to playful).
- Describe what you want; only a short noun "Avoid:" list at the end (Flow has no negative-prompt field).
- One identity sentence per character, "<Name> = the person in the <Name> reference image: ...". flow-mcp adds no
  lock of its own (`builder_lock`), so nothing contradicts it.
- Opponents are a cast entry `"kind": "extra"` with a concrete contrasting `look` and a `count`.
- Fights: `sides.staging` must put the opponents IN FRONT of the allies, facing them (e.g. "Sam and Lina on the
  left facing right; the guards on the right facing left"). Opponents "behind"/"in the background" during a fight
  is refused; a beat that mixes a fighting move with "each other" is refused; an ally as `target` of an ally is refused.
- Faces: three-quarter toward camera, medium or medium-wide; never start a character in side profile.
- Wide shots with main characters are refused ("too wide for faces") unless the scene sets `"allow_wide": true`:
  measured face similarity was 0.36-0.46 on wide shots vs 0.52-0.63 on medium shots (pass line 0.50). Use
  "medium-wide shot" or "medium shot".
- Outfits go in the first subject line ("Main characters: Sam (black jacket), Lina (olive jacket)"): at the end of the
  prompt they were dropped and both men got the same grey jacket.
- Nobody shown dead or out cold: "defeated guards lie still" was refused by Flow (no tile, no charge). Write "sit on
  the floor, dazed, holding their arms". The builder refuses dead/bodies/lie still/motionless/unconscious.
- Every fight scene opens with one second where the main characters face the camera in a clear three-quarter view
  at medium distance (the face moment the model locks identity on), and opponents get an exact count.
- flow-mcp waits for each scene's own tile before the next submit: a prompt Flow drops without a tile is reported as
  refused (not charged) instead of shifting later clips onto the wrong scenes; "unusual activity" stops the batch.
- `--only` uses storyboard scene ids in both `build_prompts.py` and `run_stage.mjs` (stage scenes carry `scene_id`).
