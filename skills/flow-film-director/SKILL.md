---
name: flow-film-director
description: Direct any kind of video in Google Flow (flow MCP) with consistent, accurate subjects - short films, shot-for-shot remakes of a reference video, talking heads, product ads, explainers, social reels, music videos, place tours, animated or stylised films, animated photos, event recaps. People keep the SAME face, products and places stay identical, actions look real. Use whenever the user wants a video, film, reel or ad made with Flow, wants to copy a reference video with their own people, or complains that Flow changes faces, loses details or makes fake or funny actions ('keep my exact face', 'same characters', 'same actions as this video', 'a product ad', 'animate this photo'). Deterministic gated pipeline - required idea or reference video, intent profile, cleaned references, measured face/object/motion checks, storyboard.json compiled into exact prompts, verified keyframes, measured review of every clip, assembly and final watch.
version: 1.3.0
declared-hosts:
  - labs.google         # Google Flow, through the user's own signed-in browser session (flow MCP)
  - 127.0.0.1           # local Voicebox app on this computer (loopback only, enforced in code)
  - pypi.org            # pip packages, one-time setup only
  - files.pythonhosted.org
  - github.com          # OpenCV Zoo public face models, one-time setup only
  - raw.githubusercontent.com
  - storage.googleapis.com  # Google MediaPipe public pose model, one-time setup only
  - huggingface.co      # Chatterbox public voice weights, downloaded by the library on first local use
env-vars: []
---

# Flow Film Director

Goal: a video where every face matches the real photos, every product and place stays the same, every action is physically believable, and - with a reference
video - every shot copies the reference. Nothing moves on until its gate passes, and every gate has a measured number
AND a written visual check.

**Deterministic means:** the same inputs give the same requests and the same decisions. Prompts are compiled from
`storyboard.json` by a script (never improvised), choices between variants follow a fixed ranking, thresholds are
fixed, every decision and every credit is logged. Flow itself has no seed, so takes still vary - the fixed gates are
what make the *result* repeatable. **About "100%":** no video model copies a face perfectly. The skill guarantees that
nothing reaches the film unless it measured at real-footage level and passed the feature-by-feature check. Say this
once to the user, then work.

## Two modes - pick in Phase 1 (default: fast)
- **fast** (`"mode": "fast"`, references/fast-mode.md): videos straight from the Flow characters (Ingredients) in
  human-paced parallel batches, builder-owned prompt, measured review, one retake round. Measured ~1.5 min per scene
  (5 clips in 5.8 min). Use for stories, ads, reels, action.
- **precise** (`"mode": "precise"`): the full gated pipeline below (verified start/end keyframes per scene).
  Use for shot-for-shot remakes and hero shots.
Both need flow-mcp with the skill's patch: `python scripts/patch_flow_mcp.py --check` (apply without --check).
Never retry right away after Flow says "We noticed some unusual activity": stop and wait.

## Why Flow made bad videos before (each rule below fixes one)

| Root cause | What it looks like | Fix in this skill |
|---|---|---|
| Video from text + `reference_images` only: the model *approximates* the face | "a cousin", nose/jaw/beard change per shot | Animate FROM a verified keyframe (`first_frame`): the identity is in the pixels |
| Long `chain_previous` chains, unverified continuation frames | Face drifts a bit more every clip | Every scene starts on its own verified keyframe; no chaining by default |
| Big, fast or vague actions, head turns, hands over the face | Morphing, rubber limbs, melting faces | One small action with start + end, face visible, 4-8 s |
| Small faces in wide shots | Face invented from 40 pixels | Face >= ~15 % of frame height when identity matters |
| Bad / conflicting reference photos | The model averages them into nobody | Measured audit; user decides each conflict; only clean refs go to Flow |
| Phone screenshots used as references | App bars, captions and icons leak into scenes | `prep_refs.py` crops them; audit flags screenshots |
| Product/place only described in words | Packaging, label or building changes per shot | Clean photo in every still + `object_check.py` gate |
| Two characters who look alike | Features blend or swap | `differences` sentence + optimal face assignment in every check |
| Prompts rewritten by hand each time | Results change for no reason | Prompts compiled from storyboard.json |
| Reference video "described", not measured | A different video comes out | Measured breakdown + motion_match gate per shot |
| Nobody watched the result | Bad clips in the film | Every still and clip measured + watched; failures regenerated |

## Tools

- **flow MCP**: `flow_status`, `flow_character`, `flow_character_edit`, `flow_characters`, `flow_generate`, `flow_wait`,
  `flow_assets`, `flow_download`, `flow_edit`, `flow_retry`, `flow_assemble`, `flow_narrate`, `flow_transcribe`,
  `flow_captions`. Downloads land in `~/flow-mcp-out/<project>/`. **Every file path given to the MCP must be
  absolute** (it resolves paths in its own folder, not the project).
- **Scripts** (`<skill_dir>/scripts/`, run with the skill's own Python `PY` from Phase 0):

  | script | what for |
  |---|---|
  | `setup_env.py` | one-time isolated env `~/.flow-film/venv` (mediapipe, opencv, numpy pinned) + models |
  | `ref_audit.py` | audit reference photos, pick upload-worthy refs, build the identity gallery |
  | `identity_check.py` | score stills/clips per character; `ranking` = fixed choice among variants; exit 0 PASS, 1 not, 2 error |
  | `ref_video_breakdown.py` | split a reference video into shots; measure camera, framing, people, timed body events |
  | `motion_match.py` | compare a generated clip with its reference shot; pose score, camera, positions, trim window |
  | `build_prompts.py` | compile `storyboard.json` into the exact `flow_generate` requests (validated) |
  | `object_check.py` | is the product / object / place the same one as in its photos (SIFT + geometry); stills and clips |
  | `prep_refs.py` | clean reference photos: crop phone-screenshot UI, bars, borders (Flow copies whatever it sees) |
  | `contact_sheet.py` | side-by-side sheets (refs vs generated, or clip frames) |
  | `run_stage.mjs` | send a built stage file to Flow through flow-mcp (parallel), wait, report wall time and credits |
  | `cast_check.py` | gate for a character's source picture and saved Flow portrait (one face, PASS, face >= 0.18 of picture height) |
  | `fast_review.py` | measured review of a fast round: face score per scene -> keep / retake list (`--only` ready) |
  | `patch_flow_mcp.py` | check / apply the flow-mcp patch the skill needs (parallel, builder_lock, exact character attach) |
  | `assemble.py` | the film from accepted takes: trims, audio mode (native / soundtrack / voiceover / mixed), beat-snapped cuts, -14 LUFS; writes `<film>.timeline.json` |
  | `edit_video.py` | `locate` film time -> scene/take, `frame` grab, `apply` edits (cut, splice, speed, freeze, text, logo, blur, zoom, color, audio) |
  | `setup_voice_env.py` | one-time voice env `~/.flow-film/voice-venv` (Chatterbox, GPU if present); prints `VPY` |
  | `voice_profile.py` | (VPY) learn a character's voice from samples, save it with the character, measure any audio against it |
  | `voice_convert.py` | (VPY) `clip`: the character speaks with their own voice, same timing and picture; `speak`: new lines in that voice |
- **/watch-video** skill: frames + transcript for the realism review.
- Read every sheet image yourself. Numbers catch identity and geometry; only your eyes catch fake actions.

Reference files - load when the phase needs them:
`references/intents.md` (Phase 1: every kind of video, its inputs and checks) · `references/reference-video.md` (replicate mode, phases R1-R7) · `references/character-bible-template.md` (phase 2) ·
`references/storyboard-schema.md` (phase 4) · `references/prompt-recipes.md` (realism rules, actions that break,
models) · `references/review-rubric.md` (checklists, thresholds, defect -> fix) · `references/audio.md` (voices,
soundtrack, mix) · `references/editing.md` (Phase 8) · `references/videodb.md` (optional cloud search/indexing).

## Working folder - all state lives here (survives new sessions)

```
film/<slug>/
  brief.md          idea / reference answers, approved deviations, decisions log
  reference/        breakdown.json/.md, shots/shot-NN/ (replicate mode only)
  bible/            audit.md, gallery.json, <Name>/sheet.jpg, best/, golden/, <Name>.md, <Name>.lock.txt
  storyboard.json   THE source of every prompt (schema: references/storyboard-schema.md)
  prompts/          built by build_prompts.py - never hand-edited
  keyframes/        accepted stills (+ _rejected/)     clips/   accepted takes (+ _identity/, _match/)
  review/           scene-NN.md: scores, defects, decision per still and take
  ledger.md         every credit: date, tool, scene, take, credits, result
  voices/           <Name>/profile.json, reference.wav, embedding.npy (character voices)
  final/            film-vN.mp4 + film-vN.timeline.json + final review
```
On resume: read brief, storyboard.json, ledger, review/; continue at the first scene without `accepted.clip`.

## Phase 0 - Preflight (no credits)
1. `flow_status`. If it returns a hint, relay it and stop. Note the credit balance.
2. `python "<skill_dir>/scripts/setup_env.py"` (once; safe to repeat). It prints `PY=<path>`: use that interpreter for
   every script below. `ffmpeg -version` must work.
3. Use ONE Flow project for the whole film (characters exist per project).
4. Only if a character will speak with a real voice: `python "<skill_dir>/scripts/setup_voice_env.py"` (once, ~3-4 GB;
   prints `VPY=<path>` for the voice scripts).

## Phase 1 - The idea is mandatory: a written prompt OR a reference video, and the intent
Ask first: **"Do you have a reference video to copy, or will you describe the video in writing?"** Do not continue,
do not suggest a story, until the user gives one of these. Then name the **intent** with the user from
`references/intents.md` (story, remake, talking head, product ad, explainer/voice-over, social reel, music video,
places tour, animated/stylised, animate a photo, event recap, invented characters, comedy - or a mix) and collect
that intent's required inputs from its table. The intent sets `intent`, `style_mode` and the defaults in
storyboard.json and decides which measured checks gate each still and clip.

**A. Reference video (replicate mode)** - the user wants THEIR people in THAT video. Follow
`references/reference-video.md` R1-R4: which part, who becomes whom, what may change; breakdown; the agent writes the
beat-by-beat memory per shot; the user approves it (Gate R). The storyboard then mirrors the reference one shot per
scene. Never add, drop, merge, re-order or "improve" a shot; deviations only with explicit OK, logged in brief.md.

**B. Written prompt (original mode)** - the user writes the idea. It must contain, or you ask until it does:
purpose and audience, story/message in 2-3 sentences, length, aspect (9:16 / 16:9), every recurring subject (people,
characters, products, places) with photos or descriptions, tone (realistic unless the user chooses a style), what
must NOT happen, dialogue/voice-over/singing, music, wardrobe, credit budget - plus the intent's own inputs.
Then propose the scene list (one shot per scene, 4/6/8 s each; 60 s ~ 9-12 scenes) and go scene by scene: who,
where, framing (prefer medium close-up / medium), start state, the ONE action, end state, camera (one move), dialogue
(~2.5 words/s). Replace actions that break (table in prompt-recipes.md) with realistic versions - with the user.

**Audio - always ask (references/audio.md):** what the viewer hears - `native` (clips' own sound), `soundtrack`
(music for the whole film: **ask for the soundtrack file path**, start point, cuts on the beat or not), `voiceover`
or `mixed` (dialogue + music that dips under speech); and for each speaking character: stock Flow voice, or their
REAL voice from samples the user gives (only people who agreed). Write the `audio` block and any `voice` per cast entry.

Both modes: write `brief.md`. **Gate 1: user approves the scene list, the audio plan (and in mode A the reference memory).**

## Phase 2 - Clean references + forensic subject analysis (no credits)
0. Clean every reference photo first (people, products, places): `"%PY%" prep_refs.py <folder> --out <folder>/clean --auto`,
   read `_sheet.jpg`; for phone screenshots (story/app captures) re-run with `--crop-top/--crop-bottom` until only the
   photo is left, or exclude it. Flow copies app bars, captions and icons into the scene. Use only `clean/` from now on.
   Products/objects/places: write a short lock per item (shape, proportions, materials, colours, label layout - no
   readable text) into `cast`; their verification is `object_check.py` in Phase 3. Stylised characters: a design sheet
   (front, 3/4, side) drawn as stills and approved by the user replaces photos. Invented people: draw portrait stills,
   the user approves them, and they become the reference folder for the audit below.
1. People: `"%PY%" ref_audit.py --char Sam="<folder>" --char Lina="<folder>" --out film/<slug>/bible` (all characters in
   one run, so their similarity to each other is measured).
2. Read `audit.md`, every `<Name>/sheet.jpg` and the crops. Note what numbers miss: cartoons/illustrations, AI edits,
   beauty filters, glasses on/off, different beard/hair between photos, mirrored selfies.
3. Ask the user about every conflict; remove excluded photos from the folder used and re-run the audit.
4. Decide the **film wardrobe** now (it decides how the character is created in Phase 3).
5. Fill `references/character-bible-template.md` -> `bible/<Name>.md`, one feature at a time, measured words only.
   Write the differences between characters and the 60-110 word lock -> `bible/<Name>.lock.txt`.
6. **Gate 2: user confirms the bible + lock + chosen refs.**

**Voices** (characters with real-voice samples): `"%VPY%" voice_profile.py create --name <Name> --samples <files> --out
film/<slug>/voices`; gate `ok: true` (>= 8 s clean speech, one speaker; 30-60 s is best). Put
`"voice": "voices/<Name>/profile.json"` in that cast entry and use the profile's `flow_voice_hint` when creating the
Flow character. Ask for more/cleaner samples on any flag.

## Phase 3 - Lock the characters in Flow, prove it on free stills (0 credits)
The MCP adds a CHARACTER LOCK to every scene that references `asset:<Name>` and that lock demands *the same clothes as
the character's picture*. So the character's picture must already wear the film outfit:
- **Picture gate first:** `"%VPY%" cast_check.py --gallery film/<slug>/bible/gallery.json --name <Name> <candidate photos>`
  and use only its `best` (exactly one face, PASS, face >= 0.18 of the picture height). Never a full-body, distant or
  night photo: a night photo with a tiny face (share 0.10) made every video give that person a rounder, heavier face. Flip mirrored selfies (text reads backwards)
  first. After `flow_character`, run cast_check again on the saved `_cast/<Name>.*` portrait. To replace a bad
  character: `flow_character_edit(name, rename_to="<Name>-old")`, then create the new one under the real name.
- a real photo in the film outfit exists -> `flow_character(name, image=<that photo, absolute>)`;
- otherwise -> generate stills of the person in the film outfit with the best photos as `reference_images`
  (`max_credits: 0`), keep one that passes identity_check at still level and the visual check, then
  `flow_character(name, image=<that still>)`.
Then `flow_character_edit(name, look=<lock text>)` with NO `change` (a `change` makes Flow redraw the portrait in
16:9 and the real photo is gone). `flow_characters` must list them. Stylised characters are created the same way
from their approved design still. Products, objects and places are NOT Flow characters: they go in `cast` with a
clean photo as `ref`; prove them with 3-4 free stills each and
`"%PY%" object_check.py --ref <clean photos> --name <Item> <stills>` (rigid things; soft things and stylised art:
visual check only).

Verification set (one `flow_generate`, images, `max_credits: 0`, absolute paths): per character front head-and-
shoulders, 3/4 left, 3/4 right, profile, medium standing, talking/smiling; plus a two-shot when 2+ characters.
`reference_images`: `["asset:<Name>", <best frontal>, <best 3/4>]` (max 3). Prompt: "Verification still" recipe.
Score: `"%PY%" identity_check.py --gallery film/<slug>/bible/gallery.json --expect <Name> --pass-min 0.55 --pass-max 0.60 <stills>`
then a refs-vs-stills sheet with `contact_sheet.py`, and the feature checklist (review-rubric.md).
**Gate 3:** every still PASS (a profile still may be WEAK only under the rubric's rule), no critical feature mismatch,
the two-shot keeps both identities. Fixes, max 5 rounds, one change per round: (a) put the failing feature first in
the lock, explicit (`look=` update, no `change`); (b) re-create the character from another real photo / passing
still; (c) swap the 2nd/3rd reference; (d) `model: "Nano Banana Pro"` for stills. Passing stills -> `bible/<Name>/golden/`.

## Phase 4 - Storyboard -> verified keyframes (0 credits)
1. Write `film/<slug>/storyboard.json` (references/storyboard-schema.md) from brief.md - in mode A from the breakdown
   and the agent notes (shot size, camera, positions, beats with times, `ref_shot`, `ref_window` for shots > 10 s).
2. `"%PY%" build_prompts.py film/<slug>/storyboard.json`. Exit 1 = fix every listed error and rebuild. Read `plan.md`.
3. `flow_generate` with `prompts/stage1-start-keyframes.json` **as is**; `flow_wait` until finished.
4. Per scene run the checks its subjects need (intents.md "Which checks run where"): people ->
   `identity_check.py --expect <people in scene> --pass-min 0.55 --pass-max 0.60 <variants>`; products/places ->
   `object_check.py --ref <clean photos> --name <Item> <variants>`; stylised -> visual style check. Take the first file
   that passes every check, in the `ranking` order of the people check (else of the object check); check it against the scene text (and in mode A side by side with the
   reference keyframe: framing, positions, every limb, gaze, props). If the top one fails the visual check, take the
   next passing one; none -> change ONE storyboard field, rebuild with `--only <id>`, regenerate.
5. Copy the accepted file to `keyframes/scene-NN-start.png`, write its absolute path into `accepted.start`, rebuild,
   run stage 2 (END frames - a separate call, built from the accepted START, never `reference_previous`), accept
   `accepted.end` the same way. START and END must be the same moment seconds apart: same people, clothes, light, set,
   camera.
6. Log scores and choices in `review/scene-NN.md`; show the user a contact sheet of all keyframes in order.
   **Gate 4: every keyframe PASS + user approves the keyframe board.** Only now can anything cost credits.

## Phase 5 - Animate (credits - ask first)
1. Rebuild; `plan.md` shows stage 3 and its expected credits. Tell the user the per-scene and total cost; get an
   explicit OK within the budget. Every video scene has an explicit `model` (exact label), Omni duration 4/6/8/10,
   Veo no duration/resolution - the builder enforces it.
2. `flow_generate` with `prompts/stage3-video.json` as is; `flow_wait` to the end; log every spend in `ledger.md`
   immediately. If a paid job vanishes from the queue, check `flow_assets` before re-running anything.
3. Not in the default pipeline: `chain_previous` (cannot carry a verified first frame) and `flow_continue` (agent
   mode, no quote). Only if the user asks for a continuous take - as a separately approved spend
   (`acknowledge_cost: true`), then the full Phase 6 review on the result.

## Phase 6 - Review every clip, fix, repeat
For EACH take:
1. Identity: `identity_check.py --expect <people> --every 0.25 <clip>`; read the identity sheet and the worst frame.
   Products/places in the clip: `object_check.py --ref <clean photos> --name <Item> <clip>`. Spoken or sung lines:
   `flow_transcribe` the clip and compare with the script word by word.
   Characters with a voice profile: `"%VPY%" voice_convert.py clip --profile <Name>=voices/<Name>/profile.json
   --in <take> --out <take>.voiced.mp4` (several speakers: `--map`); gate `all_pass`, timing change < 42 ms; then
   transcribe the voiced take and compare the words; store it as `accepted.clip_voiced`.
2. Mode A: `motion_match.py <clip> --breakdown film/<slug>/reference/breakdown.json --shot shot-NN [--window a b]`;
   read the side-by-side sheet and `largest_differences`; its `trim` goes into the scene.
3. Realism: `/watch-video` on the clip (or `contact_sheet.py --video <clip> --at 0,15,30,45,60,75,90,100`), then the
   clip checklist and score in review-rubric.md.
4. Decide (write it in `review/scene-NN.md`):
   - all gates pass -> `accepted.clip` (+ `trim`), copy to `clips/`;
   - defects only in the last 1.0 s or the first 0.5 s and the rest still covers the planned length -> accept with
     `trim` (same rule as the rubric);
   - fixable -> the defect -> fix table; change ONE storyboard field, `build_prompts.py --only <id>`, regenerate;
   - small local change on an otherwise perfect clip -> `flow_edit` (~20 credits, no quote; ask first);
   - 3 failed takes -> stop, explain the pattern, propose a simpler version (mode A: an approved deviation).
   Ask before each paid retake unless the user set a retake budget.
5. **Gate 6:** every scene has `accepted.clip`.

## Phase 7 - Assemble and final watch
1. Speech: `flow_transcribe` -> user confirms the words. Narration: a recorded file, `flow_narrate`, or a character's
   own voice with `voice_convert.py speak` (Voicebox engine by default; every voice engine runs on this computer).
2. `"%PY%" assemble.py film/<slug>/storyboard.json --out film/<slug>/final/film-v1.mp4` - uses each scene's
   `accepted.clip_voiced`/`accepted.clip` and `trim`, the `audio` block (soundtrack path, start, fades, beat-snapped
   cuts, ducking, voice-over), -14 LUFS two-pass. Read its report (duration, BPM, cut moves, loudness).
   Mode A: total length = reference window (within 0.2 s per shot); reference audio in sync at every cut.
3. Final: `identity_check.py --every 0.5` on the film, `/watch-video` on the film (cuts, continuity of clothes, props
   and light, audio levels, music under dialogue, story). Fix with the Phase 6 loop or Phase 8, re-assemble, re-check.
4. Captions if wanted: transcribe -> confirm -> `flow_captions`.
5. Deliver: film path, credits from the ledger, per-scene identity / motion / voice scores, approved deviations, limits.

## Phase 8 - Edit exact frames, scenes and periods (references/editing.md)
The user names a time ("0:12-0:15 the hand is wrong", "cut 0:20-0:23", "add the price at 0:30"):
1. `edit_video.py locate --timeline final/film-vN.timeline.json --range a b` -> scene, take, take time; say it back.
2. Pick the cheapest fix that solves it (table in editing.md): free edits (cut, speed, freeze, text, logo, blur, zoom,
   color, mute/replace audio, insert a still) or a regenerated period (retake of that scene through the gates, then
   `splice` the same period) - credits only with the user's OK.
3. `edit_video.py apply --timeline ... --edits edits/vN.json --out final/film-v(N+1).mp4`; check the changed period
   with the identity/object checks and the frames around every boundary; keep every version.


## Security & Network Access Disclosures

Flow Film Director reads no API keys, tokens or custom environment variables and stores no secrets. The user's
reference photos and prompts go only to Google Flow (the video generator the user is already signed in to);
voice recordings never leave the computer. Every outbound connection is listed here:

| Host | When | Why | What is sent |
|---|---|---|---|
| labs.google (Google Flow) | generation phases, through the flow MCP | make keyframes and clips in the user's own Flow project | prompts, and the cleaned reference images / keyframes the user approved |
| 127.0.0.1 (port 17493, configurable in ~/.flow-film/voicebox.json) | voice steps | the user's own Voicebox desktop app on the same computer | voice samples and text, never leaving the machine; the host is fixed in code and system proxies are ignored |
| pypi.org, files.pythonhosted.org | `setup_env.py`, `setup_voice_env.py`, once | install pinned Python packages into ~/.flow-film venvs | nothing (download only) |
| github.com, raw.githubusercontent.com | `setup_env.py`, once | OpenCV Zoo YuNet + SFace face models into ~/.flow-film/models | nothing (download only) |
| storage.googleapis.com | `setup_env.py`, once | Google MediaPipe pose model into ~/.flow-film/models | nothing (download only) |
| huggingface.co | first use of the local Chatterbox engine | public Chatterbox voice weights (the library's own download) | nothing (download only) |

`setup_env.py` is the only skill script that opens a URL itself, and it reads no user files. All analysis scripts
(face, object, motion, review, assembly, editing) work offline. Video generation goes through the user's own,
already signed-in Google Flow MCP session. Shell commands run without a shell (argument lists only: ffmpeg, git,
`npm run build` of the user's local flow-mcp checkout after `patch_flow_mcp.py` applies its patch).

## Hard rules
- No phase starts before the previous gate passes. No idea or reference video -> no work.
- Never spend credits without the user's OK for that batch; stills always `max_credits: 0`.
- Never hand-write or edit a prompt: change storyboard.json and rebuild.
- Never accept a still or clip without the scripts AND your own look at the sheets.
- Never put a character in a video without a verified keyframe of that exact scene.
- Mode A: never change the reference's shots, order, timing, framing, camera or actions without explicit OK.
- Never describe a real person against their photos; never beautify, de-age or slim.
- No funny, exaggerated or impossible actions unless the user asked in Phase 1 (then `allow_words`, logged). One
  action + one camera move per scene. Never ask Flow to draw readable text, logos or prices: add them in post.
- Never send an uncleaned reference (screenshot UI, captions, other people) to Flow.
- Voices: only people who agreed; never a public figure. Soundtrack mode needs the user's file path - never invent music.
- VideoDB or any other cloud tool is not part of this skill: use it only if the user installed it and said yes to that upload (references/videodb.md).
- If the user says the result looks wrong, believe them, find the gate that let it through, tighten that gate.
- Explain in simple English (B1-B2); short status lines: phase, scene, take, scores.
