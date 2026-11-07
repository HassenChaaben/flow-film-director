# How it works

The agent follows [`SKILL.md`](../skills/flow-film-director/SKILL.md). This page explains the phases and the
reasoning behind each gate.

## Why animate from keyframes

Flow can make video in two ways:

- **R2V (reference to video)**: text + reference images. The model *re-imagines* the person from the references,
  so every clip is a slightly different person.
- **I2V (image to video)**: a first frame (and optionally a last frame). The person is already in the pixels;
  the model only has to move them.

flow-mcp's own measurements show the two cannot be combined in one request. So the skill spends its effort on
**free stills** (Nano Banana, 0 credits) until every keyframe is right, then animates *from* them (I2V).
Identity comes from the keyframe; the motion prompt only describes movement.

## Phases and gates

| Phase | What happens | Gate |
|---|---|---|
| 0 Preflight | `flow_status`, Python env, models, ffmpeg | Flow signed in |
| 1 Brief | written idea **or** reference video; intent; required inputs; scene list | user approves |
| R Reference (remakes) | `ref_video_breakdown.py`: shots, camera, framing, people, timed body events; agent writes the beat-by-beat memory | user approves the memory |
| 2 Subjects | `prep_refs.py` cleans photos; `ref_audit.py` measures them; bibles + locks | user confirms bibles |
| 3 Lock in Flow | Flow characters from real photos in the film outfit; verification stills | identity / object check + feature checklist |
| 4 Keyframes | `storyboard.json` -> `build_prompts.py` -> start stills -> end stills | every keyframe passes + user approves the board |
| 5 Animate | stage-3 requests, credits approved | - |
| 6 Review | identity over time, object sameness, motion match, realism checklist; reshoot one change at a time | every scene accepted |
| 7 Assemble | trims, voice, music, `flow_assemble`, captions, final watch | final film passes |

## Determinism

Flow has no seed, so two takes of one request differ. What the skill makes repeatable:

- **Prompts** are compiled from `storyboard.json` by `build_prompts.py` with fixed templates and validation. Same
  storyboard, same requests. A retake changes a field in the storyboard (logged), never the prompt by hand.
- **Selection** among variants follows a fixed ranking (passing first, then the highest worst-character score).
- **Thresholds** are fixed numbers, calibrated on real footage (see the README).
- **Analysis** is rule-based: fixed sampling rates, sequential decoding, fixed cut/camera/pose rules.
- **State** is files: brief, storyboard, reviews, ledger. A new session continues where the last one stopped.

## The measurements

- **Face identity** (`identity_check.py`): OpenCV YuNet finds faces, SFace turns each face into an identity vector,
  each face is compared with the reference gallery (mean of the 3 best matches). In a two-person frame faces are
  assigned to characters by the best total score, so look-alikes are not swapped. Clips are sampled every 0.25 s;
  drift (identity falling for 2+ samples), missing faces and extra faces are reported.
- **Object / place sameness** (`object_check.py`): SIFT keypoints + RANSAC homography against the clean product or
  place photos. Counts details that agree in *position*, so a similar-looking but different product fails.
- **Reference motion** (`ref_video_breakdown.py`, `motion_match.py`): shots are cut by colour-histogram change;
  camera motion from a robust similarity transform between frames; bodies from MediaPipe Pose (whole frame plus
  left/right halves, so several people are found), tracked and normalised to body size. A generated clip is slid
  over its reference shot to find the best alignment; the pose score is the mean joint distance there. The same
  alignment gives the trim window.
- **Realism** is checked by the agent on contact sheets and with the watch-video skill, using the rubric in
  `references/review-rubric.md`.

## Files the agent writes

```
film/<slug>/
  brief.md          idea / reference answers, approved deviations, decisions log
  reference/        breakdown.json/.md, shots/shot-NN/ (remakes)
  bible/            audit.md, gallery.json, sheets, best/, golden/, <Name>.md, <Name>.lock.txt
  storyboard.json   the source of every prompt
  prompts/          built requests (never hand-edited)
  keyframes/ clips/ accepted stills and takes
  review/           scores, defects and decisions per scene
  ledger.md         every credit spent
  final/            film + final review
```
