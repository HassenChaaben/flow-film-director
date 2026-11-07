# Quality guide - how to get accurate, realistic results

The skill enforces most of this by itself. Knowing *why* helps you give better inputs and approve the right things.

## 1. References decide the ceiling

| Do | Don't |
|---|---|
| 5-10 sharp photos per person, face at least ~300 px tall | blurry, tiny, far-away faces |
| front, 3/4 left, 3/4 right, profile, one full body | only selfies from below |
| same period of life (same hair, beard, weight) | photos from different years mixed |
| natural light, no filters | beauty filters, AI-edited "improved" photos, cartoons of the person |
| one person per photo | group photos (the model may borrow a stranger's features) |
| originals | phone screenshots of stories (status bar, captions, icons leak into scenes - `prep_refs.py` crops them, originals are better) |

Products: front, back, 3/4 and label close-up, on a plain background. Places: the actual spot, several angles,
the same time of day you want in the film.

The audit (`ref_audit.py`) measures how alike your photos are (the "baseline"), flags outliers (another person,
heavy filter, different era) and picks the photos that go to Flow. When it asks you about a conflict - glasses on or
off, short or long beard - your answer decides what every scene will show.

## 2. Decide the look before generating

- **Outfit**: Flow's character lock copies the clothes of the character picture. Pick the film outfit first; the skill
  creates the character from a photo (or a verified still) in that outfit.
- **Glasses, beard, hair**: one version for the whole film.
- **Two people who look alike**: say how to tell them apart (height, hair, beard, clothes colour). The skill writes a
  "differences" sentence into every two-person shot.

## 3. Write scenes Flow can actually do

One scene = one shot = **one small, physical action with a start and an end**, 4-8 seconds.

| Breaks | Works |
|---|---|
| "they walk through the city" | "two slow steps toward the camera, then he stops and smiles" |
| "he turns around to face her" | start already three-quarter to the camera, small head turn |
| hugs, handshakes, high-fives | hand already on the shoulder in the start frame |
| "he eats breakfast" | "he lifts the cup and takes one sip" |
| "she types an email" | hands resting on the keyboard, she looks up |
| "funny face", "laughs hysterically" | "a short quiet laugh, gentle smile" |
| an object appears in his hand | the object is already in the hand in the start frame |
| 15 seconds of continuous action | two scenes with their own keyframes |

Faces must be big enough: medium close-up or medium shot for anything where identity matters. Wide shots invent faces.

## 4. Approve keyframes like a director

The video is animated *from* the start frame (and towards the end frame). Whatever is wrong in a keyframe will be
wrong in the clip. On the keyframe board check: each face, hands (five fingers, natural grip), clothes, props, the
light direction, the background, nobody extra, no text. START and END must be the *same moment* a few seconds apart.

## 5. Choose the model per shot

| Shot | Model |
|---|---|
| Most shots, drafts, transitions between two frames | Omni 1.1 Flash 720p (7-15 credits) |
| Speech, lip-sync, complex natural body motion | Veo 3.1 - Fast (20 credits, 8 s) |
| A hero shot after everything else is approved | Veo 3.1 - Quality (100 credits, ask first) |

## 6. Budget for reshoots

The review loop is where quality comes from. Plan about **1.5-2x** the credits of a single pass. The skill changes
one thing per retake (framing, action size, duration, end frame, model) so each retake teaches something.

## 7. Remakes of a reference video

- Choose a part with clear shots (not a 2-minute action sequence with 60 cuts).
- Tell the agent exactly who becomes whom and what may change (faces only? clothes? location?).
- Read the shot memory it writes (beats with times) - this is what will be copied.
- Fast fights, crowds and stunts are rated "high risk": accept more retakes or an approved simplification.

## 8. Text, logos, prices, subtitles

Never inside Flow - it garbles letters. Titles, logos and prices are added in post; subtitles with `flow_captions`
after you confirm the words.

## 9. Sound

Dialogue is generated with the clip (Veo is best at it): one speaker per clip, ~2.5 words per second, mouth visible.
Narration and music are added at assembly; scenes without dialogue get "Nobody speaks" so mouths stay still.
