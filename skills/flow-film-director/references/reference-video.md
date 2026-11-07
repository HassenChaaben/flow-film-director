# Replicate mode: the user gave a reference video

Promise to the user: **the film is the reference video, shot for shot, with their people.** Same number of shots, same
order, same length, same framing, same camera moves, same blocking (who stands where), same actions at the same
moments. Only what the user explicitly asked to change is different (usually: faces, clothes, location). Never
"improve", re-order, merge or invent shots. Every difference from the reference needs the user's explicit OK, and
is written in `brief.md` under "Approved deviations".

## Step R1 - pick the part (ask)
- Which part of the video? (start/end seconds). Long sources: analyse only that window (`--start/--end`).
- Who in the reference becomes whom? (P1 = Sam, P2 = Lina...). Look at `shots/shot-NN/sheet.jpg` together.
- What changes: faces only, or also clothes / location / props? What must stay exactly the same?
- Is there speech or music to keep? (`flow_transcribe` on the reference for the exact words and timing.)

## Step R2 - break it down (measured, no credits)
```
"%PY%" "<skill_dir>/scripts/ref_video_breakdown.py" "<video>" --out film/<slug>/reference --start <s> --end <e>
```
Gives per shot: start/end/duration, shot size, camera move (pan/tilt/push-in/pull-out/handheld/static), people with
screen position, timed body events (hand height, posture, facing, travel), pose speed, risk level, keyframes at
0/25/50/75/100 %, 8 fps frames, pose tracks. Same input -> same output.

## Step R3 - memorise the meaning (agent, by reading frames)
For EVERY shot, read `sheet.jpg` and then the 8 fps `frames/` beat by beat. Under each shot in `breakdown.md` fill
"Agent notes" with facts only, in this order:
1. Mapping: P1 = <Name>, P2 = <Name>.
2. Start state of each person: posture, where the weight is, head direction, gaze target, each hand (where, holding what).
3. Beats with times (to 0.1 s), physical verbs: "1.2-1.9 s P1 lifts right hand from hip to collar, fingers pinch the collar".
   Use the measured events as the time skeleton; never contradict them without saying why.
4. End state of each person.
5. Expression changes with times. Speech: who, words, times.
6. Camera: the measured move + its speed (slow/medium), what it ends framing.
7. Set, light direction and colour, props, anything moving in the background.
8. What makes this shot recognisable (the detail a viewer would miss if it changed).
This is the memory the whole film is built from; the user approves it (Gate R).

## Step R4 - map to scenes (deterministic)
- One reference shot = one scene. A shot longer than 10 s = several scenes with `ref_window` (cut at a natural pause,
  where the measured events show stillness).
- `duration`: leave it out - the builder picks the shortest allowed length that holds the shot + 0.5 s; the extra is
  trimmed with `trim` from motion_match.
- Very short shots (< 1.5 s, fast cutting): still one scene each; generate 4 s and trim. Never merge them.
- `characters[].ref_person`, `position` from the breakdown; `start`/`end` from the agent notes (start / end state).
- `beats`: the agent-note beats converted to clip time (subtract the shot/window start), same verbs, same order.
- `shot.size` and `shot.camera_move`: copy the measured values (same words).
- Risk high (fast fight, crowds, contact, whip pans): tell the user honestly before generating; offer more takes or an
  approved simplification. Do not simplify silently.

## Step R5 - keyframes that copy the composition
The builder puts the reference keyframe (0 % for START, 100 % for END) in the references as a *composition reference*
and tells Flow to copy angle, framing, positions and body poses but not faces, costumes or location. Check every still:
- identity_check PASS for each character (the model must not copy the actor's face);
- side by side with the reference keyframe (`contact_sheet.py --title REF <ref kf> --title GEN <stills>`):
  same framing and shot size, same positions left/right, same pose of every limb, same gaze, same props.
Reject on any visible pose difference - small details are the point of replicate mode.

## Step R6 - clips must pass motion_match
```
"%PY%" "<skill_dir>/scripts/motion_match.py" <clip> --breakdown film/<slug>/reference/breakdown.json --shot shot-NN [--window a b]
```
PASS needs: no cut, same people count and order, positions within 0.15 of frame width, shot size within one step,
same camera move words, pose score >= 0.70 (calibrated: the reference against itself 0.83-0.98, an unrelated clip
~0.25). Read the side-by-side sheet and the `largest_differences`. Write the returned `trim` into the scene.
Then identity_check and the realism review as usual. A clip is accepted only when motion_match, identity_check and
the rubric all pass.

## Step R7 - assemble to the reference timeline
Cut each accepted clip to its `trim`, assemble in reference order. The total length must equal the reference window
(within 0.2 s per shot). If the user kept the reference audio/music, lay it under the film and check sync at every cut.
