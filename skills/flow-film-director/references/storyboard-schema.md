# storyboard.json - the single source of truth for every prompt

`scripts/build_prompts.py film/<slug>/storyboard.json` turns this file into the exact flow_generate requests.
Change the film by changing this file and rebuilding - never by hand-editing a prompt. Paths may be relative to
this file; the builder makes them absolute (the MCP refuses relative paths).
The `//` comments below are explanations only - the real file is plain JSON without comments.
A complete working example: `examples/storyboard.example.json` in the repository.

```jsonc
{
  "flow_project": "FriendsCafe60",           // output folder for videos; stills go to "<flow_project>-keyframes"
  "intent": "story",                         // id from references/intents.md (story, remake, talking-head, product-ad, explainer,
                                             //   social-reel, music-video, places, animated, animate-photo, event, invented, comedy)
  "style_mode": "photoreal",                 // "photoreal" (default) or "stylized"
  "style": "natural colour, documentary look",   // photoreal: optional extra; stylized: REQUIRED (line, palette, rendering)
  "style_refs": ["style/ref-01.png"],        // stylized: style reference image(s); the first goes into every still
  "allow_words": [],                         // words the user explicitly approved that are normally banned (e.g. comedy: "funny")
  "aspect_ratio": "9:16",                    // 16:9 or 9:16 only (video)
  "default_model": "Omni 1.1 Flash",         // exact Flow labels: "Omni 1.1 Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality"
  "resolution": "720p",                      // Omni only: 360p | 720p
  "reference_breakdown": "reference/breakdown.json",   // only in replicate mode (intent "remake")
  "audio": {                                 // what the viewer hears (references/audio.md) - ALWAYS decided in Phase 1
    "mode": "mixed",                         // native | soundtrack | voiceover | mixed
    "soundtrack": {"file": "music/track.mp3", "start": 12.0, "volume_db": 0, "fade_in": 0.5, "fade_out": 2.0,
                   "loop": true, "snap_cuts_to_beats": true, "max_shift": 0.5},   // required for mode soundtrack
    "voiceover": [{"file": "vo/line-01.wav", "at": 0.0}],                       // mode voiceover
    "clip_volume": 1.0,                      // default: native/mixed 1.0, voiceover 0.25, soundtrack 0.0
    "target_lufs": -14,
    "allow_clip_music": false                // false: every clip prompt says "No music in the clip."
  },
  "differences": "Sam is the taller one with tight dark curls and a short beard; Lina has straight shoulder-length hair.",
  "cast": {                                  // everything that must look the same in every shot
    "Sam":    {"kind": "person",  "ref": "asset:Sam",  "lock_file": "bible/Sam.lock.txt",  "outfit": "plain white shirt, beige trousers",
               "voice": "voices/Sam/profile.json",    // optional: speaks with his real voice (voice_profile.py create)
               "costume_approved": false},          // true = the user approved a costume (e.g. from a remake); describe it generically
                                                    // in "outfit" (no franchise names); prompts add "no mask, face fully visible,
                                                    // keep the face over any suit detail"; create the Flow character from a verified
                                                    // still of the REAL face already wearing that outfit
    "Lina":   {"kind": "person",  "ref": "asset:Lina", "lock_file": "bible/Lina.lock.txt", "outfit": "navy t-shirt, dark jeans"},
    "Bottle": {"kind": "product", "ref": "refs/bottle-front.png", "lock": "Bottle: tall frosted-glass bottle, matte black cap, blank cream label."},
    "Cafe":   {"kind": "place",   "ref": "refs/cafe-terrace.png"}
  },                                         // kinds: person | character (stylised/animal/mascot) | product | object | place
                                             // person/character: "ref" "asset:<Name>" = the Flow character (the MCP adds its lock);
                                             // product/object/place: "ref" = a clean photo path (lock text goes into the prompt)
  "scenes": [
    {
      "id": 1,
      "title": "Sam waits at the cafe table",
      "ref_shot": "shot-03",                 // remake: which reference shot this scene copies
      "ref_window": [0.0, 6.2],              // optional: part of the shot (s from shot start); needed when the shot > 10 s
      "skip_ref_frame": true,                // optional: skip composition ref frame (prevents weapon policy triggers or likeness dilution)
      "use_ref_frame": false,                // scenes with 2+ people get NO composition frame unless this is true (identity needs every slot)
      "allow_profile": false,                // optional: allow 90° pure side profile (default false: 3/4 frontal required for likeness)
      "allow_wide": false,                   // optional: allow wide shot (default false: medium shot required for likeness)
      "duration": 8,                         // Omni: 4|6|8|10. Leave out in remake mode (auto). Veo: always 8, leave out
      "model": "Omni 1.1 Flash",             // optional, overrides default_model
      "variants": 4,                         // stills per keyframe call (0 credits; if Flow quotes credits the call is skipped -> use 1-2)
      "max_credits": 12,                     // video cap; default = the expected cost
      "shot": {"size": "medium close-up", "angle": "eye-level", "lens": "50mm", "camera_move": "static locked-off camera"},
      "location": {"description": "small cafe terrace, round marble table, green awning", "image": "refs/cafe-terrace.png"},
      "light": "late afternoon sun from camera-left, soft fill",
      "characters": [                        // people / characters in frame (may be empty: product, landscape, place shots)
        {"name": "Sam", "ref_person": "P1", "position": "left third",
         "start": "sitting at the table, back straight, right hand next to a white cup, looking at the phone in his left hand",
         "end": "sitting, phone lowered to the table, looking up toward screen-right with a small smile",
         "expression": "relaxed, then a small closed-mouth smile"}
      ],
      "subjects": [                          // products / objects / places in frame (optional)
        {"name": "Bottle", "start": "standing on the table next to the cup, label toward camera"}
      ],
      "background_people": "",               // e.g. "two blurred passers-by far behind" (faces never recognisable); empty = nobody else
      "beats": [                             // the timed actions of the VIDEO, seconds from the clip start; who can be "camera"
        {"from": 0.0, "to": 2.0, "who": "Sam", "action": "scrolls once on the phone with his thumb"},
        {"from": 2.0, "to": 3.5, "who": "Sam", "action": "lowers the phone flat onto the table"},
        {"from": 3.5, "to": 6.0, "who": "Sam", "action": "lifts his head and looks toward screen-right, a small smile"}
      ],
      "props": ["white ceramic cup", "black smartphone"],
      "start_moment": "The quiet moment before his friend arrives.",
      "end_moment": "He has just noticed his friend arriving.",
      "dialogue": [{"who": "Sam", "line": "There you are.", "mode": "says"}],   // mode "sings" for music videos; none -> "Nobody speaks"
      "sound": "quiet cafe ambience, distant street",
      "use_end_frame": true,                 // false for loops, packshots, animate-photo shots
      "accepted": {"start": "keyframes/scene-01-start.png", "end": "keyframes/scene-01-end.png", "clip": "clips/scene-01.mp4",
                   "clip_voiced": "clips/scene-01.voiced.mp4"},   // voiced take (voice_convert.py) - assembly prefers it
      "trim": [0.4, 6.6]                     // the part of the clip that goes in the film (from review / motion_match)
    }
  ]
}
```

Rules the builder enforces (it exits 1 and lists every error):
- the look flow-mcp stores for each character (~/.flow-mcp/characters.json, appended to every scene) must equal the
  bible lock word for word and pass the word checks; no cast name may be a prefix of another, and `flow_project` may
  not start with a cast name (Flow could attach a tile instead of the character);
- curly/wavy hair in a person's lock needs a length in cm; "profile"/"side view" in any start/end/beat text is refused
  unless `allow_profile` (three-quarter wording is fine);
- every name in `characters` / `subjects` exists in `cast` with the right kind; every lock file and path exists;
- products, objects and places have a photo `ref`; stylized mode has a `style`;
- model label is exact; Omni duration is 4/6/8/10; Veo has no duration/resolution;
- a reference shot longer than 10 s must be split with `ref_window`;
- no banned words in the storyboard text (comic/stylised words unless the mode or `allow_words` allows them; film and
  franchise names always); no request for readable text ("a sign that says ...") - text goes in post;
- audio: mode is one of the four; mode soundtrack needs `audio.soundtrack.file` (ask the user for the path) and allows
  no dialogue (use mixed); every `voice` profile and the soundtrack file must exist;
- `max_credits` is not below the expected cost (otherwise Flow would silently skip the scene);
- at most 3 references per still, fixed priority: characters -> subjects -> accepted START (END frames only) ->
  style reference -> composition frame from the reference shot -> location photo. Dropped ones are listed in `scene-NN.md`;
- each stage only contains open work (`accepted.start` / `accepted.end` / `accepted.clip` close it); `--only 3,5` for retakes.
