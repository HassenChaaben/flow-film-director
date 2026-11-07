# Video intents - pick one in Phase 1, it decides inputs, checks and rules

Every intent runs the same pipeline (bible -> storyboard.json -> keyframes -> clips -> review -> assembly). The intent
only changes: what the user must give, which subjects are locked, which measurements gate the result, and the
storyboard defaults. Write the chosen intent in `brief.md` and in `storyboard.json` (`"intent"`). If a request mixes
two (e.g. a product ad with a presenter), use the union of their inputs and checks.

Subject kinds in `cast` (storyboard.json): `person` (photoreal human - identity_check applies), `character`
(stylised / animated / animal / mascot - visual check), `product` and `object` (object_check applies), `place`
(a location that must stay the same - object_check on the location photo).

| # | Intent | User must give | Locked subjects | Measured gates | Defaults |
|---|---|---|---|---|---|
| 1 | **Remake a reference video** (any genre) | the video + part to use + who becomes whom | people / products in it | identity_check + **motion_match** + object_check | replicate mode, `references/reference-video.md` |
| 2 | **Story / short film** with real people | written idea, photos of each person | persons | identity_check | photoreal, 4-8 s scenes, medium close-ups |
| 3 | **Talking head / UGC / testimonial / presenter** | photos, the exact script, language, voice | the speaker | identity_check + transcript check (`flow_transcribe` vs script) | 9:16, Veo 3.1 - Fast for speech, one sentence per clip (~2.5 words/s), mouth visible |
| 4 | **Product ad / commercial / e-commerce** | product photos (front, back, 3/4, label), brand colours, claims | product (+ presenter) | **object_check** on every still and clip (+ identity_check for a presenter) | packshot + use + benefit + end card; logos/text added in post |
| 5 | **Explainer / tutorial / documentary with voice-over** | the narration script (or topic), visuals wanted | whatever recurs | per subject | narration first: `flow_narrate` / user voice -> scene lengths follow the narration; "Nobody speaks" in clips |
| 6 | **Social reel / short-form (TikTok, Reels, Shorts)** | idea, hook, platform | as needed | per subject | 9:16, hook in the first 2 s, 4-6 s scenes, bold captions (`flow_captions`) |
| 7 | **Music video / lyric video** | the song file, lyrics, BPM (or the agent measures it), performers | performers | identity_check; cuts on the beat grid | scene length = whole beats; lip-sync only on chosen lines (Veo); music laid in `flow_assemble` |
| 8 | **Travel / real estate / location tour / landscape** | photos of the places, route/order | places | object_check on each place | no people (or blurred background people), slow camera moves, 6-8 s |
| 9 | **Animated / stylised** (cartoon, anime, 3D, clay, watercolour) | style reference images, character designs (or descriptions) | characters (style) | visual style check (identity_check does not apply to drawings) | `style_mode: "stylized"` + `style` text; style refs in every still |
| 10 | **Animate photos / memorial / old pictures / portrait to life** | the photos | the people in them | identity_check against the photo itself | the photo IS `accepted.start`; tiny natural motion (breathing, blink, slight smile, slow push-in), 4-6 s |
| 11 | **Event / wedding / birthday recap** | photos of the people, places, order of moments | persons + place | identity_check + object_check | short warm scenes, music-led |
| 12 | **Invented characters** (no real photos) | a description of each character | characters | identity_check on the approved portrait set | Phase 3 creates the portrait, the user approves it, `ref_audit.py` on the approved stills makes the gallery |
| 13 | **Comedy sketch / exaggerated style** (only when the user asks) | idea, which exaggerations are wanted | as needed | per subject | `allow_words` lists the approved comic words; realism of faces/hands still required |

## Required inputs - ask until you have them (Phase 1)
All intents: purpose and audience, platform, total length, aspect ratio (video 16:9 or 9:16), language, tone, what
must NOT appear, credit budget, music/voice decision. Then the intent's own column above. Never invent a missing input:
propose one concrete option and get a yes.

## Intent-specific rules
- **Product (4):** shoot the product from the same sides the photos show; never ask Flow to write the brand name or
  claims (it garbles text) - put text, logo and price in post (captions or an ffmpeg overlay). Hands holding a product:
  the product is already in the hand in the START keyframe. Rotating packshots: slow orbit, 6-8 s, plain background.
- **Talking head (3) / music (7):** one speaker per clip, line short enough for the clip, face toward camera, mouth
  visible. Check every spoken line with `flow_transcribe` and compare with the script word by word.
- **Voice-over (5):** make or record the narration first; measure each sentence (transcribe word times); scene
  durations are the sentence lengths rounded up to 4/6/8/10 s, then trimmed to the sentence.
- **Music (7):** beat length = 60 / BPM s. Cut points on whole beats (or bars = 4 beats); each clip is trimmed so its
  cut lands on a beat. Ask for the BPM or count it from the track with the user.
- **Stylised (9):** the style must be identical in every still: give 1-2 style reference images in every keyframe,
  describe line, palette, rendering in `style`. `cartoon`, `anime`, etc. are allowed words in this mode.
- **Animate photos (10):** keep motion tiny; big motion invents a different face. Crop/extend the photo to the video
  aspect first (still image, free) and check identity on the extended still.
- **Places (8):** a place reference goes in every still of that place; check it with object_check; keep the camera slow.
- **Comedy (13):** exaggeration in expression and timing only - anatomy, physics of objects and identity stay real.

## Which checks run where
| Check | Runs when | Script |
|---|---|---|
| Face identity | any `person` in the still/clip | `identity_check.py` |
| Product / place sameness | any `product`, `object` or `place` in the still/clip | `object_check.py` |
| Copy of the reference | replicate mode | `motion_match.py` |
| Spoken words | any dialogue, singing or narration | `flow_transcribe` vs script |
| Style, actions, realism, continuity | always | your eyes + `review-rubric.md` + `/watch-video` |
