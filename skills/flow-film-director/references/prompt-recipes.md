# Prompt recipes for realistic Flow output

Flow has no memory between scenes. Every prompt must carry everything: who, exact look (lock), where, light, action.
Order that works: subject + action -> shot size + camera -> location -> style -> lighting -> sound/dialogue.
English only. Positive, concrete, physical words. One shot, one action, one camera move.

## Realism block (append to every keyframe and every motion prompt)
"Photorealistic, shot on a full-frame cinema camera, natural skin texture with visible pores, real proportions,
natural motion at real-time speed, physically plausible, subtle natural expressions, no exaggeration, no cartoon,
no CGI look, no text, no logos, no watermark, no extra people, no duplicated characters, consistent lighting."

## Verification still (phase 3)
"<shot: head-and-shoulders portrait | three-quarter view facing left | right profile | medium shot standing> of
<Name>, looking <into the lens / to the left>, neutral relaxed expression <or: gentle closed-mouth smile>. Plain
light-grey studio background, soft even key light from the front-left, 85mm lens, sharp focus on the eyes.
<LOCK TEXT>. <REALISM BLOCK>"
Why plain background: it removes everything except the face, so the identity check is fair.

## Keyframe (phase 4)
"<Shot size: close-up / medium close-up / medium shot / medium-wide>, <eye-level|slightly low> angle, <35|50|85>mm lens.
<Name A> is <exact pose: standing / sitting on X>, <torso orientation>, <head direction>, looking <at B / at lens / at
object>, <right hand: exact position and what it holds>, <left hand: ...>, <expression in physical words: slight smile,
eyebrows relaxed>. <Name B> is <...>, positioned <left/right of frame, distance from A>.
Location: <from the background photo: concrete details - walls, furniture, colours>. Time: <late afternoon>,
light: <warm sun from camera-left through a window, soft fill>. Moment: <the start / end state of the action in one
sentence>.
<LOCK A>. <LOCK B>. <Differences sentence: "Sam is the taller one with tight dark ringlets; Lina has ...">.
<REALISM BLOCK>"
Rules:
- Faces at least ~15% of the frame height (prefer medium close-up to medium for dialogue).
- Hands visible and doing something specific, or out of frame; never "hands gesturing".
- Keep props few and simple (cup, phone, book). Avoid screens with readable content, written signs, mirrors.
- START and END keyframes: copy the START prompt, change only the action stage sentence (+ small pose change).

## Motion prompt (phase 5, with first_frame / last_frame)
"The shot begins exactly on the provided first frame. <One action, physically: 'Lina slowly lifts the white cup from
the table to his mouth with his right hand, takes one small sip, and lowers it halfway'>. <Others: 'Sam stays seated,
watching him, and nods once'>. <Camera: 'Static locked-off camera' | 'very slow push-in'>. Real-time speed, natural
weight and timing, faces stay the same people as in the frame for the whole shot, <ends on the provided last frame>.
<Sound: 'quiet cafe ambience, cup clink'>. <Dialogue: 'Lina says: \"...\"' - only if planned>. <short LOCK, 25-40 words
each>. <REALISM BLOCK>"
- Duration (4/6/8/10 s): the action must fill it. ~1 simple action per 4 s. Too long for the action = aimless fidgeting.
- Dialogue: ~2.5 words/second max, one speaker per clip if possible, mouth visible.

## Actions that break (and the realistic version)
| Breaks | Do instead |
|---|---|
| Pure 90° side profile walking (face is 35px, glasses distort into goggles) | Three-quarter view (30-45° toward camera), medium shot where face is >100px |
| Walking toward/away from camera for several steps, running | 2-3 slow steps across frame at medium shot, or start/stop walking |
| Head turning from profile to front (face rebuilds) | Start already 3/4 to the camera, small head movement |
| Hugs, handshakes, high-fives, hands touching faces | Stand side by side, one hand on shoulder already placed in the keyframe |
| Eating, drinking big gulps, typing, writing, playing an instrument | One sip, one bite raised to mouth, hands resting on keyboard |
| Dancing, jumping, fighting, sport | Ask user; usually cut to reaction shot instead |
| Crowd interactions, many people | Background blurred, no faces; keep cast to 1-2 people |
| "He laughs hysterically", "funny face" | "Gentle smile, a short quiet laugh" |
| Objects appearing/changing (phone in hand from nowhere) | Prop already in the start keyframe |
| Long continuous take > 8 s | Split into two scenes with two keyframe pairs |
| Very fast camera, whip pans, drone orbits around faces | Static, slow push-in, slow pan, gentle handheld |

## Subject Likeness Invariants (Glasses, Hair, and Reference Portraits)
- **Glasses**: describe the glasses of the chosen reference photo exactly - frame shape, rim thickness, colour, material, lens tint (e.g. `grey see-through rounded-square plastic frames, clear lenses`). A generic phrase draws generic glasses: `thin-framed` produced wire frames on a person whose real frames are thick plastic (forensic run, 2026-11-04). Only jargon such as `keyhole`, `goggles` is banned. If the photos disagree (glasses on/off, two different frames), the user chooses ONE before any character is created.
- **Three-Quarter Frontal Angle**: When identity matters, never frame subjects in a pure 90° side profile wide shot. Always use a 3/4 frontal view (angled 30-45° toward camera) so both eyes, eyebrows, glasses lenses, nose bridge, and jawline are in view with at least 100px face resolution.
- **True Hair Texture**: Never force a "tight buzz cut flat to head" on someone with naturally textured (wavy or coily) hair. Keep the person's true hair silhouette: altering hair volume changes skull proportions and destroys face recognition.
- **Hair**: wavy, coily or ringlet hair always gets a length in cm, the side length and what stays visible (`tight ringlets about 3 cm on top, short tapered sides, ears and forehead visible`). The texture word alone produced a 6-10 cm mop. build_prompts.py refuses a textured-hair lock without a length.
- **Asymmetric marks** (mole, scar, parting): confirm the side on a photo that is NOT a selfie - front cameras mirror.
- **Reference portrait background**: plain or soft backgrounds are a safe default; a busy tiled background was measured harmless for identity (the tiled portrait self-scores 0.94), so do not discard a sharp frontal photo for that alone.

## Banned words (they push the model to stylised or comic output)
epic, dramatic action, hilarious, funny, crazy, cartoon, anime, superhero, explosive, insane, viral, exaggerated,
dynamic pose, flying, magical, glowing, "Deadpool"/movie names (also copyright), "like a movie star".

## Model choice (use these EXACT labels - Flow matches its menu text, "Veo 3.1 Fast" without the dash fails)
- Stills: leave `model` out (newest Nano Banana, 0 credits) and always `max_credits: 0`; "Nano Banana Pro" when a
  feature keeps coming out wrong. If Flow quotes credits for x2-x4 variants the call is skipped: use fewer variants.
- Draft and default video: "Omni 1.1 Flash", `duration` 4/6/8/10 only (never 5 or 7), `resolution` "720p"
  (7/10/12/15 credits for 4/6/8/10 s). Supports first + last frame.
- Complex natural motion or speech: "Veo 3.1 - Fast" (20 credits, fixed 8 s: send NO duration and NO resolution).
  "Veo 3.1 - Lite" 10, "Veo 3.1 - Quality" 100 (explicit OK only).
- Always set `model` on video scenes: without it Flow keeps whatever model was last selected and the credit plan is wrong.
- If a model keeps failing the same scene, try the other one with the SAME keyframes before rewriting the scene.
- Prompts are built by `scripts/build_prompts.py` from storyboard.json; these templates are what it writes.
