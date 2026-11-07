# Review rubric

Two inputs for every decision: the identity numbers (identity_check.py) and your own feature-by-feature look at the
sheet. If they disagree, the stricter one wins.

## Identity numbers (identity_check.py, SFace, top-3 mean against the reference gallery)
- baseline = how alike the real photos are (leave-one-out, near-duplicates removed), from the audit.
- Clips: PASS >= 0.50 (default). Calibrated 2026-11-04: a real 73 s webcam video of the subject scored mean 0.59 / PASS;
  a lookalike "cousin" lands 0.30-0.45. WEAK 0.363-0.50. FAIL < 0.363 or face not found.
- Stills (verification stills and keyframes) are stricter, because the keyframe is where the clip's identity comes
  from: run with `--pass-min 0.55 --pass-max 0.60`.
- Profile and heavy shadow lower scores: a deliberate profile still may be WEAK if the visual check is clean AND the
  same person passes frontally in the same set/scene. This is the only accepted WEAK.
- Choosing among variants: take the first file in `ranking` (passing first, then highest worst-character score) -
  always the same rule, never "the one that looks nicer" unless the visual check rejects the top one.

## Object numbers (object_check.py, SIFT + homography against the clean photos)
- PASS inliers >= 40 and ratio >= 0.25; WEAK >= 15; FAIL below. Calibrated 2026-11-04: the same place re-framed/re-lit
  1130 inliers, a slow zoom video of it 672, different streets 9-13. Clean refs first: screenshot UI matched falsely (370).
- Rigid things only; for clothes, food, animals and stylised art use the visual check.

## Still / keyframe checklist (mark each: OK / minor / FAIL)
Identity (critical - any FAIL = reject): face shape - hairline and hair texture - eyebrows - eye shape/spacing -
nose bridge and tip - lips and smile - facial hair pattern/density - skin tone - glasses rule - age/weight unchanged.
Body: height relation between characters - build - hands (5 fingers, natural size, natural grip) - posture.
Scene: right moment of the action - props right and few - wardrobe per bible - background matches location photo -
light direction/time - no extra people, no duplicates, no text/logos - face big enough - composition leaves room for
the motion.
Accept a keyframe only with zero critical FAIL and at most 2 minor.

## Clip checklist (watch at 1-2 fps + full speed; in replicate mode compare to the reference shot side by side)
1. Identity holds at start, middle, end (no drift in identity sheet; worst frame still PASS or WEAK only on a turned head).
2. The action is the one in the brief, starts, completes, and is not repeated or looped.
3. Speed is real-time; no slow motion, no sudden accelerations, no frozen character while others move.
4. Anatomy: hands/fingers stable, no extra limbs, no limb through objects or bodies, neck/shoulders not stretching.
5. Physics: objects have weight, liquids behave, feet stay on the ground, sitting people stay sitting, no sliding.
6. Face: eyes blink naturally, gaze plausible, no melting/morphing during movement, teeth stable while talking.
7. Speech: lips match the line, only the right person talks, words correct (flow_transcribe if unsure).
8. Props and wardrobe do not change, appear, or vanish; background and light are stable.
9. Camera does what was asked; no random cuts or zooms; no text, watermark, or extra people appearing.
10. Tone: nothing comic, exaggerated, or "AI-looking" (plastic skin, glowing eyes, over-smooth motion).
Score 0-2 per item (2 = clean). Accept: items 1, 2, 4, 6 = 2 and total >= 18/20. Usable-with-trim: defects only in
the last 1.0 s or the first 0.5 s, AND what remains is still at least the planned length -> write `trim` in the
storyboard. (Same rule in SKILL.md.) In replicate mode also motion_match PASS on the trimmed part.

## Defect -> fix
| Defect | Most likely cause | Fix (change one thing per retake) |
|---|---|---|
| Face becomes a "cousin" from the start | Weak keyframe / R2V used | Re-check keyframe identity; animate from first_frame only |
| Face drifts mid-clip | Head turn, fast move, occlusion, small face | Smaller action, closer framing, keep face toward camera, shorter clip |
| Face changes near the end | End frame too different / no end frame | Add an end keyframe close to the start, or trim |
| Two characters swap/blend features | Similar descriptors | Add the differences sentence; keep them apart in frame; check both locks |
| Action not done / loops / fidgets | Vague action or clip too long | Name one action with a clear end; reduce duration |
| Fake or comic action | Prompt words, impossible action | Use the realistic version table; remove banned words |
| Slow motion / floaty | Model default for calm prompts | "real-time speed, natural weight and timing"; try other model |
| Bad hands / objects | Complex interaction | Prop placed in keyframe, hands simpler, or hide hands |
| Extra person / duplicate | Crowded location, vague cast | "exactly two people in the frame", empty background |
| Background shifts | Location not fixed | Background photo as reference in keyframes; static camera |
| Wrong lip sync / wrong speaker | Two speakers, long line | One speaker per clip, shorter line, mouth visible |
| Jump between scenes (clothes, light) | Keyframes made separately | Same `outfit`/`light` text in storyboard.json for all scenes; a golden still as reference |
| Action differs from the reference shot (mode A) | Beats vague or mistimed | Rewrite the scene's beats from the frames at 8 fps with exact times; END keyframe = reference end pose |

## review/scene-NN.md format
```
# Scene NN - <title>
Brief: <one line>
## Keyframes
| file | <Name> score | <Name> score | visual | decision |
## Takes
### Take K - <model> <duration>s <credits> credits
identity: <Name> mean/min/verdict ...; issues: ...
checklist: 1:2 2:1 ... total NN/20
defects: t=2.5s right hand fingers merge; ...
decision: accept | trim 0.0-5.2 | retake (change: ...) | escalate
```
