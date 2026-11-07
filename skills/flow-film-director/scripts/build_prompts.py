"""Turn film/<slug>/storyboard.json into the exact flow_generate requests. Same storyboard -> same requests.

Usage:
  python build_prompts.py film/<slug>/storyboard.json [--only 3,5]
Each stage holds only OPEN work: a scene with accepted.start is not in stage 1, with accepted.end not in stage 2,
with accepted.clip not in stage 3. --only limits every stage to those scene ids (retakes).
Writes next to the storyboard, in prompts/:
  stage1-start-keyframes.json   flow_generate args: START stills (images, 0 credits, N variants)
  stage2-end-keyframes.json     END stills for scenes with use_end_frame and an accepted START
  stage3-video.json             video scenes whose keyframes are accepted (first/last frame)
  scene-NN.md                   the prompts in readable form
  plan.md                       what each stage contains, what is missing, credit estimate for stage 3
The agent passes these JSON files to flow_generate AS THEY ARE. To change a prompt, change storyboard.json and
rebuild - never hand-edit a prompt (that is how runs stop being reproducible). Exit 1 on any validation error.

Works for every intent (references/intents.md): people, stylised characters, products, objects, places, scenes with
no people, dialogue / singing / silent, photoreal or stylised. Storyboard format: references/storyboard-schema.md.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

OMNI = "Omni 1.1 Flash"
VEO = {"Veo 3.1 - Lite": 10, "Veo 3.1 - Fast": 20, "Veo 3.1 - Quality": 100}  # fixed 8 s
OMNI_COST = {"720p": {4: 7, 6: 10, 8: 12, 10: 15}, "360p": {4: 4, 6: 5, 8: 6, 10: 7}}
DURATIONS = (4, 6, 8, 10)
KINDS = ("person", "character", "product", "object", "place", "extra")
DEFAULT_TONE = "Grounded, serious, cinematic realism"
# Fast mode states what we WANT (Google's Veo guide: describe, do not instruct with "no/don't"); the few exclusions
# are a short noun list at the end, because Flow has no negative-prompt field.
FAST_REALISM = "Photoreal live action, real proportions, natural motion, same faces and clothes from start to end."
FAST_MAX_CHARS = 1800
FAST_AVOID = "Avoid: duplicated people, morphing faces, extra limbs, on-screen text."

REALISM = ("Photorealistic, shot on a full-frame cinema camera, natural skin texture with visible pores, real human "
           "proportions, physically plausible, subtle natural expressions, no exaggeration, no cartoon, no CGI look, "
           "no text, no logos, no watermark, no extra people, no duplicated characters, consistent lighting.")
REALISM_MOTION = ("Real-time speed with natural weight and timing, physically plausible movement, faces and bodies stay "
                  "exactly the same people as in the first frame for the whole shot, hands keep five fingers and hold "
                  "objects firmly, products and objects keep their exact shape and design, no morphing, no slow motion, "
                  "no sudden cuts, no comedy or exaggeration, no text.")
REALISM_MOTION_PLAYFUL = ("Expressions and timing may be playful as described, but anatomy, hands, the physics of objects "
                          "and every face stay real and identical to the first frame; no morphing, no sudden cuts, no text.")
STYLE = ("Art style: {style}. Keep exactly the same art style, line quality, colour palette and character designs as "
         "the reference images, consistent rendering in every shot, no mixing with other styles, no text, no logos, "
         "no watermark, no extra characters, no duplicated characters.")
STYLE_MOTION = ("Keep exactly the art style, character designs and colours of the first frame for the whole shot, "
                "smooth natural motion at real-time speed, no morphing, no sudden cuts, no text.")
ALWAYS_BANNED = ["deadpool", "wolverine", "marvel", "like a movie star", "iconic", "unmasked", "hood down"]  # film/franchise names: copying risk + refusals
REALISM_BANNED = ["epic", "hilarious", "funny", "crazy", "cartoon", "anime", "superhero", "explosive", "insane", "viral",
                  "exaggerated", "dynamic pose", "flying", "magical", "glowing"]
SAFETY_BANNED = [
    "pistol", "pistols", "gun", "guns", "rifle", "rifles", "shotgun", "shotguns",
    "revolver", "revolvers", "firearm", "firearms", "weapon", "weapons", "bullet", "bullets",
    "ammunition", "shooting", "kill", "murder", "blood", "gore", "severed", "decapitate",
    # people shown as dead or out cold: "defeated guards lie still on the floor" was refused by Flow with no
    # charge and no tile (live 2026-11-06); write "sit on the floor, dazed, holding their arms" instead
    "dead", "corpse", "corpses", "bodies", "lie still", "lies still", "lying still", "motionless",
    "unconscious", "knocked out", "lifeless"
]
STYLIZED_OK = {"cartoon", "anime", "magical", "glowing", "flying"}
TEXT_ASK = re.compile(r"\b(text|caption|title|headline|words?|logo|sign|label)\b[^.]{0,40}\b(says|saying|reads|reading|written|spelling)\b", re.I)
GLASSES_BANNED = re.compile(r"\b(keyhole|round goggles|circular lenses|thick round glasses|welding goggles|steampunk goggles)\b", re.I)
HAIR_CONTRADICTIONS = re.compile(r"\b(buzz\s*cut|crew\s*cut\s*flat|shaved\s*head|flat\s*to\s*head)\b", re.I)


class Bad(Exception):
    pass


def absolute(base: Path, p: str | None) -> str | None:
    if not p:
        return None
    if p.startswith("asset:"):
        return p
    q = Path(p)
    q = q if q.is_absolute() else (base / q)
    q = q.resolve()
    if not q.exists():
        raise Bad(f"file not found: {q}")
    return str(q)


def sentence(s: str | None) -> str:
    s = (s or "").strip()
    return "" if not s else (s if s.endswith((".", "!", "?")) else s + ".")


def kind(cast: dict, name: str) -> str:
    return (cast.get(name) or {}).get("kind", "person")


def lock_text(base: Path, cast: dict, name: str, words: int | None = None) -> str:
    c = cast.get(name) or {}
    f = c.get("lock_file")
    txt = (base / f).read_text(encoding="utf-8").strip() if f and (base / f).exists() else (c.get("lock") or "")
    if not txt:
        if c.get("kind") == "place":
            return ""
        raise Bad(f"{name}: no lock text (cast.{name}.lock_file or cast.{name}.lock)")
    if words:
        txt = " ".join(txt.split()[:words]).rstrip(",;.") + "."
    return txt


def nearest_frame(frames_dir: str, t: float) -> str | None:
    files = sorted(Path(frames_dir).glob("t*.jpg"))
    return str(min(files, key=lambda f: abs(float(f.stem[1:]) - t))) if files else None


def load_shot(sb: dict, base: Path, shot_id: str | None, window=None):
    """Reference shot record; with window [a, b] (seconds from the shot start) only that part of the shot."""
    if not shot_id:
        return None
    bd_path = sb.get("reference_breakdown")
    if not bd_path:
        raise Bad(f"scene uses ref_shot {shot_id} but storyboard has no reference_breakdown")
    bd = json.loads(Path(absolute(base, bd_path)).read_text(encoding="utf-8"))
    shot = next((dict(s) for s in bd["shots"] if s["id"] == shot_id), None)
    if shot is None:
        raise Bad(f"{shot_id} not in {bd_path}")
    if window:
        a, b = float(window[0]), float(window[1])
        if not (0 <= a < b <= shot["duration"] + 0.05):
            raise Bad(f"ref_window {window} is outside {shot_id} (0 - {shot['duration']} s)")
        shot["duration"] = round(b - a, 2)
        shot["keyframes"] = [{"pct": 0, "file": nearest_frame(shot["frames_dir"], shot["start"] + a)},
                             {"pct": 100, "file": nearest_frame(shot["frames_dir"], shot["start"] + b)}]
        shot["window"] = [a, b]
    return shot


def model_and_duration(sb: dict, sc: dict, shot) -> tuple[str, int | None, str | None]:
    model = sc.get("model") or sb.get("default_model") or OMNI
    if model != OMNI and model not in VEO:
        raise Bad(f"scene {sc['id']}: model must be exactly one of {[OMNI, *VEO]} (Flow matches menu labels), got '{model}'")
    if model in VEO:
        if sc.get("duration") not in (None, 8):
            raise Bad(f"scene {sc['id']}: Veo clips are fixed at 8 s; remove duration or use {OMNI}")
        return model, None, None
    res = sc.get("resolution") or sb.get("resolution") or "720p"
    if res not in OMNI_COST:
        raise Bad(f"scene {sc['id']}: resolution must be 360p or 720p")
    dur = sc.get("duration")
    if dur is None and shot:  # replicate mode: shortest allowed length that holds the reference shot + 0.5 s handle
        need = shot["duration"] + 0.5
        dur = next((d for d in DURATIONS if d >= need), None)
        if dur is None:
            raise Bad(f"scene {sc['id']}: reference {shot['id']} is {shot['duration']} s - longer than 10 s, split it with ref_window")
    if dur not in DURATIONS:
        raise Bad(f"scene {sc['id']}: duration must be one of {DURATIONS} for {OMNI} (got {dur})")
    return model, dur, res


def refs_for(sb, base, sc, which, shot):
    """Max 3 references, fixed priority: characters -> subjects (products/objects/places) -> (END: accepted START) ->
    style reference (stylised) -> composition frame (replicate) -> location photo."""
    cast = sb["cast"]
    refs = []
    for ch in sc.get("characters", []):
        refs.append(absolute(base, cast[ch["name"]].get("ref") or f"asset:{ch['name']}"))
    for sj in sc.get("subjects", []):
        refs.append(absolute(base, cast[sj["name"]].get("ref")))
    if which == "end":
        refs.append(absolute(base, (sc.get("accepted") or {}).get("start")))
    if sb.get("style_mode") == "stylized" and sb.get("style_refs"):
        refs.append(absolute(base, sb["style_refs"][0]))
    skip_comp = sc.get("skip_ref_frame") or sc.get("skip_composition_ref") or sc.get("skip_shot_frame")
    # With 2+ people every slot is needed for identity: the movie frame is opt-in there (use_ref_frame: true).
    if len(sc.get("characters", [])) >= 2 and not sc.get("use_ref_frame"):
        skip_comp = True
    if shot and not skip_comp:
        kf = next((k for k in shot["keyframes"] if k["pct"] == (100 if which == "end" else 0)), None)
        if kf and kf.get("file"):
            refs.append(absolute(base, kf["file"]))
    loc = (sc.get("location") or {}).get("image")
    if loc:
        refs.append(absolute(base, loc))
    seen, uniq = set(), []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq[:3], uniq[3:]


def count_line(sb, sc):
    chars = [c["name"] for c in sc.get("characters", [])]
    people = all(kind(sb["cast"], n) == "person" for n in chars)
    noun = ("person" if len(chars) == 1 else "people") if people else ("character" if len(chars) == 1 else "characters")
    if chars:
        line = f"Exactly {len(chars)} {noun} in the frame: {', '.join(chars)}."
    else:
        line = "No people in the frame." if not sc.get("background_people") else ""
    if sc.get("background_people"):
        line += " " + sentence(f"In the background only: {sc['background_people']}, faces not recognisable")
    return line.strip()


def keyframe_prompt(sb, base, sc, which, shot, refs):
    cast = sb["cast"]
    shot_d = sc.get("shot") or {}
    size = shot_d.get("size") or (shot or {}).get("shot_size") or "medium shot"
    parts = [f"{size[0].upper() + size[1:]}, {shot_d.get('angle', 'eye-level')} angle, {shot_d.get('lens', '50mm')} lens, "
             f"{sb.get('aspect_ratio', '16:9')} frame.", count_line(sb, sc)]
    for c in sc.get("characters", []):
        pose = c.get("end" if which == "end" else "start") or c.get("start")
        outfit = cast[c["name"]].get("outfit")
        who = c["name"] + (f", wearing {outfit}," if outfit else "")
        where = f"in the {c['position']} of the frame" if c.get("position") else ""
        parts.append(sentence(", ".join(x for x in (f"{who} is {pose.rstrip('.')}" if pose else who, where) if x)))
        if c.get("expression"):
            parts.append(sentence(f"{c['name']}'s expression: {c['expression']}"))
    for sj in sc.get("subjects", []):
        state = sj.get("end" if which == "end" else "start") or sj.get("start") or sj.get("placement")
        if state:
            parts.append(sentence(f"{sj['name']}: {state}"))
    parts.append(sentence(sc.get("end_moment" if which == "end" else "start_moment")))
    if sc.get("props"):
        parts.append(sentence("Props: " + ", ".join(sc["props"]) + "; nothing else in their hands"))
    loc = sc.get("location") or {}
    if loc.get("description"):
        parts.append(sentence(f"Location: {loc['description']}"))
    if sc.get("light"):
        parts.append(sentence(f"Light: {sc['light']}"))
    costumed = [c["name"] for c in sc.get("characters", []) if cast[c["name"]].get("costume_approved")]
    if shot and any(r == absolute(base, k["file"]) for r in refs for k in shot["keyframes"] if k.get("file")):
        if costumed:
            parts.append("Composition reference image: copy only its camera angle, framing, positions and body poses; faces, "
                         "hair, masks, logos, emblems and the location never come from this image; the outfits are the ones "
                         "described in words.")
        else:
            parts.append("Composition reference image: copy exactly its camera angle, framing, lens perspective, where each "
                         "person stands in the frame and each person's body pose and hand positions. Do NOT copy the faces, "
                         "costumes, masks, logos or the location from it: the people are only the characters named here.")
    if costumed:
        parts.append("No mask, no hood, no helmet, no emblem or logo on any outfit; every face and its hair fully visible. "
                     "If a suit detail and a face detail compete, keep the face exactly as in that person's reference image.")
    if which == "end" and (sc.get("accepted") or {}).get("start"):
        parts.append("Same moment a few seconds later as the provided start still: identical people, clothes, objects, "
                     "set, light and camera; only the action has progressed.")
    names = [c["name"] for c in sc.get("characters", [])]
    if len(names) > 1 and sb.get("differences"):
        parts.append(sentence(sb["differences"]))
    # Anything not given as a Flow character asset gets no automatic CHARACTER LOCK from the MCP: write it here.
    for n in names + [s["name"] for s in sc.get("subjects", [])]:
        if not str(cast[n].get("ref", f"asset:{n}")).startswith("asset:"):
            t = lock_text(base, cast, n)
            if t:
                parts.append(t)
    if sb.get("style_mode") == "stylized":
        parts.append(STYLE.format(style=sb["style"].rstrip(".")))
    else:
        if sb.get("style"):
            parts.append(sentence(sb["style"]))
        parts.append(REALISM)
    return " ".join(p for p in parts if p)


def motion_prompt(sb, base, sc, shot, has_end):
    cast = sb["cast"]
    parts = ["The shot begins exactly on the provided first frame."]
    beats = sc.get("beats") or []
    if not beats:
        raise Bad(f"scene {sc['id']}: no beats (the timed actions; use who='camera' for camera-only shots)")
    acting = set()
    for b in beats:
        parts.append(sentence(f"From {float(b['from']):.1f} s to {float(b['to']):.1f} s: {b['who']} {b['action']}"))
        acting.add(b["who"])
    for c in sc.get("characters", []):
        if c["name"] not in acting:
            parts.append(sentence(f"{c['name']} stays as in the first frame, only natural breathing and blinking"))
    cam = (sc.get("shot") or {}).get("camera_move") or ((shot or {}).get("camera") or {}).get("move") or "static locked-off camera"
    parts.append(sentence(f"Camera: {cam.replace(' + ', ', ')}"))
    if shot:
        parts.append("Match the timing of these beats exactly; nothing else happens.")
    if has_end:
        parts.append("The shot ends exactly on the provided last frame.")
    audio = sb.get("audio") or {}
    mode = audio.get("mode", "native")
    lines = sc.get("dialogue") or []
    if mode == "soundtrack" and lines:
        raise Bad(f"scene {sc['id']}: audio mode 'soundtrack' plays music over the whole film - remove the dialogue "
                  "or use mode 'mixed' (dialogue + ducked music)")
    for d in lines:
        verb = "sings" if d.get("mode") == "sings" else "says"
        parts.append(f'{d["who"]} {verb}: "{d["line"]}"')
    if sc.get("characters") and not lines:
        parts.append("Nobody speaks or sings; mouths stay relaxed and closed except for natural breathing.")
    sound = sc.get("sound") or ""
    if any(cast.get(d["who"], {}).get("voice") for d in lines):
        # the character's real voice is put in afterwards (voice_convert.py): clean speech converts best
        sound = (sound + ", " if sound else "") + "clean close-microphone dialogue, quiet room tone"
    if mode == "soundtrack":
        sound = "only quiet natural ambience, no speech"
    if sound:
        parts.append(sentence(f"Sound: {sound}"))
    if not audio.get("allow_clip_music"):
        parts.append("No music in the clip.")  # music is added once, at assembly, so it never jumps between shots
    for n in [c["name"] for c in sc.get("characters", [])] + [s["name"] for s in sc.get("subjects", [])]:
        t = lock_text(base, cast, n, words=40)
        if t:
            parts.append(t)
    if len(sc.get("characters", [])) > 1 and sb.get("differences"):
        parts.append(sentence(sb["differences"]))
    if sb.get("style_mode") == "stylized":
        parts.append(STYLE_MOTION)
    elif sb.get("allow_words") or sb.get("intent") == "comedy":
        parts.append(REALISM_MOTION_PLAYFUL)
    else:
        parts.append(REALISM_MOTION)
    return " ".join(p for p in parts if p)


def check_words(sb, base, sc, text, where):
    """Checks only the storyboard's own words; the fixed blocks legitimately say 'no cartoon'."""
    for fixed in (REALISM, REALISM_MOTION, REALISM_MOTION_PLAYFUL, STYLE_MOTION, "No music in the clip.", FAST_REALISM, FAST_AVOID):
        text = text.replace(fixed, "")
    text = re.sub(r"Art style: .*?duplicated characters\.", "", text)
    text = re.sub(r"Do NOT copy the faces.*?named here\.", "", text)
    text = re.sub(r"faces, hair, masks, logos, emblems.*?described in words\.", "", text)
    text = re.sub(r"No mask, no hood, no helmet.*?reference image\.", "", text)
    spoken = [d["line"] for d in sc.get("dialogue") or []]
    for line in spoken:
        text = text.replace(line, "")
    allow = {w.lower() for w in sb.get("allow_words", [])}

    # 1. Flow safety filters (weapons/violence cause deleteDelete rejections)
    safety_hits = [w for w in SAFETY_BANNED if re.search(rf"\b{re.escape(w)}\b", text, re.I) and w not in allow]
    if safety_hits:
        raise Bad(f"{where}: safety-sensitive weapon/violence word(s) {safety_hits} trigger Flow policy rejection (deleteDelete); use neutral staging (e.g. tactical combat suit, hands resting at side)")

    # 2. Likeness invariant: glasses description check
    glasses_hit = GLASSES_BANNED.search(text)
    if glasses_hit and "keyhole" not in allow:
        raise Bad(f"{where}: '{glasses_hit.group(0)}' causes diffusion models to draw steampunk/cartoon goggles; use 'modern thin-framed dark glasses with clear transparent lenses'")

    # 3. Likeness invariant: curly hair contradiction check
    cast = sb.get("cast", {})
    has_curly = False
    for n, c in cast.items():
        lt = (c.get("lock") or "")
        f = c.get("lock_file")
        if f and (base / f).exists():
            lt += " " + (base / f).read_text(encoding="utf-8")
        if "curly" in lt.lower() or "wavy" in lt.lower():
            has_curly = True
            break
    if has_curly and "flat_hair" not in allow:
        hair_hit = HAIR_CONTRADICTIONS.search(text)
        if hair_hit:
            raise Bad(f"{where}: '{hair_hit.group(0)}' contradicts character's natural curly hair; preserving natural hair silhouette and volume is required for facial recognition")

    # 4. Standard banned words
    banned = list(ALWAYS_BANNED)
    if sb.get("style_mode") == "stylized":
        banned += [w for w in REALISM_BANNED if w not in STYLIZED_OK]
    else:
        banned += REALISM_BANNED
    banned = [w for w in banned if w in ALWAYS_BANNED or w not in allow]
    hits = [w for w in banned if re.search(rf"\b{re.escape(w)}\b", text, re.I)]
    if hits:
        raise Bad(f"{where}: banned words {hits} (comic/stylised or film names; allow a style word via 'allow_words' only if the user asked for it)")
    if TEXT_ASK.search(text):
        raise Bad(f"{where}: asks Flow to draw readable text ('{TEXT_ASK.search(text).group(0)}') - Flow garbles text; add it in post (flow_captions / overlay)")


def check_looks(sb, base):
    """The identity text Flow REALLY receives: flow-mcp appends the look stored in ~/.flow-mcp/characters.json to every
    scene that uses asset:<Name>. It must be the bible lock word for word and pass the same word checks."""
    errs = []
    looks_file = Path(os.environ.get("FLOW_MCP_HOME", str(Path.home() / ".flow-mcp"))) / "characters.json"
    looks = {}
    if looks_file.exists() and not sb.get("skip_look_check"):
        try:
            looks = json.loads(looks_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            errs.append(f"{looks_file} is not valid JSON")
    for n, c in sb.get("cast", {}).items():
        if c.get("kind", "person") not in ("person", "character"):
            continue
        try:
            lock = lock_text(base, sb["cast"], n)
        except Bad:
            continue
        if c.get("kind", "person") == "person" and re.search(r"\b(curly|curls|wavy|coily)\b", lock, re.I) \
                and not re.search(r"\d+(\.\d+)?\s*(cm|mm)\b", lock):
            errs.append(f"cast.{n}: the lock says curly/wavy hair but gives no length in cm - Flow then draws a big mop; "
                        "write e.g. 'tight curls about 3 cm on top, sides short, ears and forehead visible'")
        stored = looks.get(n.lower())
        if stored is not None and str(c.get("ref", f"asset:{n}")).startswith("asset:"):
            if " ".join(stored.split()) != " ".join(lock.split()):
                errs.append(f"cast.{n}: the look stored in Flow ({looks_file}) is not the bible lock - flow-mcp appends the stored "
                            f"one to every scene. Run flow_character_edit(name='{n}', look=<lock text>) (no 'change'), then rebuild")
            try:
                check_words(sb, base, {"dialogue": []}, stored, f"stored Flow look of {n}")
            except Bad as e:
                errs.append(str(e))
    return errs


def validate(sb):
    errs = []
    if sb.get("aspect_ratio", "16:9") not in ("16:9", "9:16"):
        errs.append("aspect_ratio must be 16:9 or 9:16 (video supports only these)")
    if sb.get("style_mode", "photoreal") not in ("photoreal", "stylized"):
        errs.append("style_mode must be 'photoreal' or 'stylized'")
    if sb.get("style_mode") == "stylized" and not sb.get("style"):
        errs.append("style_mode 'stylized' needs a 'style' description (line, palette, rendering)")
    names = sorted(sb.get("cast", {}), key=str.lower)
    for a in names:
        for b in names:
            if a != b and b.lower().startswith(a.lower()):
                errs.append(f"cast names '{a}' and '{b}': one is a prefix of the other, so Flow can attach the wrong one - rename")
    proj = (sb.get("flow_project") or "").lower()
    for n in sb.get("cast", {}):
        if proj.startswith(n.lower()):
            errs.append(f"flow_project '{sb.get('flow_project')}' starts with the character name '{n}': Flow tiles named "
                        f"'{sb.get('flow_project')}-scene-NN' can be attached instead of the character 'asset:{n}'. Rename the project.")
    audio = sb.get("audio") or {}
    if audio.get("mode", "native") not in ("native", "soundtrack", "voiceover", "mixed"):
        errs.append("audio.mode must be native, soundtrack, voiceover or mixed")
    if audio.get("mode") == "soundtrack" and not (audio.get("soundtrack") or {}).get("file"):
        errs.append("audio.mode 'soundtrack' needs audio.soundtrack.file - ask the user for the soundtrack file path")
    for n, c in sb.get("cast", {}).items():
        if c.get("kind") == "extra" and not c.get("look"):
            errs.append(f"cast.{n}: an extra (enemies, crowd) needs 'look' - a concrete description that contrasts with the main characters")
        if c.get("voice") and c.get("kind", "person") not in ("person", "character"):
            errs.append(f"cast.{n}: only people and characters can have a voice profile")
        if c.get("kind", "person") not in KINDS:
            errs.append(f"cast.{n}.kind must be one of {KINDS}")
        if c.get("kind") in ("product", "object", "place") and not c.get("ref"):
            errs.append(f"cast.{n}: a {c['kind']} needs 'ref' (absolute photo path) - Flow characters are for people")
    return errs


def beats_all(sc):
    return sc.get("beats") or []


def identity_line(base, cast, n, words=45):
    c = cast[n]
    text = c.get("identity") or lock_text(base, cast, n, words=words)
    text = re.sub(rf"^\s*{re.escape(n)}\s*[:=-]\s*", "", text)
    return f"{n} = the person in the {n} reference image: {text.rstrip('.')}."


def fast_scene(sb, base, sc, model, dur, res):
    """Fast mode: one video straight from the characters as ingredients (R2V), prompt owned entirely by the builder.
    Order (Google Veo guide): tone -> shot -> who -> sides -> play-by-play -> place/light -> camera -> identity -> audio."""
    cast = sb["cast"]
    chars = [c["name"] for c in sc.get("characters", [])]
    sides = sc.get("sides") or {}
    allies = sides.get("allies") or chars
    opp = sides.get("opponents")
    shot_d = sc.get("shot") or {}
    size = shot_d.get("size") or "medium shot"
    # Measured live 2026-11-06: wide shots 0.36-0.46 face similarity, medium 0.52-0.63 (line 0.50).
    low = size.lower()
    if (any(kind(cast, n) != "extra" for n in chars) and not sc.get("allow_wide")
            and ("wide" in low or "long shot" in low) and not re.search(r"medium[- ]wide", low)):
        raise Bad(f"scene {sc['id']}: shot size '{size}' is too wide for faces (wide shots measured 0.36-0.46 face "
                  f"similarity, medium 0.52-0.63, line 0.50); use 'medium-wide shot' or 'medium shot' (or set allow_wide: true)")
    parts = [sentence(f"{sc.get('tone') or sb.get('tone') or DEFAULT_TONE}"),
             sentence(f"{size[0].upper() + size[1:]}, {shot_d.get('angle', 'eye-level, three-quarter view toward camera')}, "
                      f"{shot_d.get('lens', '35mm' if opp else '50mm')} lens")]
    # Outfits go in the FIRST subject line: placed near the end (with identity) the model dropped them and dressed
    # both men in the same grey jackets (live 2026-11-06, fight scene 2).
    dressed = [f"{n} ({cast[n]['outfit']})" if cast[n].get("outfit") else n for n in chars]
    who = f"Main characters: {', '.join(dressed)}" if chars else "No main characters"
    if opp:
        if opp not in cast or kind(cast, opp) != "extra":
            raise Bad(f"scene {sc['id']}: sides.opponents '{opp}' must be a cast entry of kind 'extra'")
        e = cast[opp]
        # "exactly": 4 guards were asked and 3 appeared (live 2026-11-06).
        who += f"; opponents: exactly {e['count']} {e['look']}" if e.get("count") else f"; opponents: several {e['look']}"
        # A guard appeared holding a rifle though none was asked for (live 2026-11-06); weapon words are refused by
        # Flow's filter, so say it positively.
        if any(b.get("target") == opp for b in beats_all(sc)):
            who += ", empty-handed"
    parts.append(sentence(who))
    fighting = bool(opp) and any(b.get("target") == opp for b in beats_all(sc))
    if opp:
        st = (sides.get("staging") or "").lower()
        # live test 2026-11-05: "guards advance from the background" put them BEHIND the heroes, who then faced the
        # camera and turned to each other - the very "they fight each other" failure. Enemies go in FRONT, facing them.
        if re.search(r"\b(behind them|behind the two|from behind|from the background|in the background)\b", st) and fighting and                 not sides.get("allow_opponents_behind"):
            raise Bad(f"scene {sc['id']}: staging puts the {opp} behind or in the background of the allies - they will face "
                      f"the camera and end up facing each other. Put the {opp} in front of the allies, facing them, e.g. "
                      f"'{' and '.join(allies)} on the left facing right; the {opp.lower()} on the right facing left'")
        if not st:
            raise Bad(f"scene {sc['id']}: a scene with opponents needs sides.staging (who stands where, who faces whom)")
        for b in beats_all(sc):
            if len(allies) > 1 and re.search(r"\beach other\b", b.get("action", ""), re.I) and not sc.get("allow_ally_conflict"):
                if re.search(r"\b(fist|punch|strike|hit|raise|fight|grab|push|kick)", b["action"], re.I):
                    raise Bad(f"scene {sc['id']}: beat '{b['action']}' mixes a fighting move with 'each other' - allies would hit each other")
    if opp:
        o = opp.lower() if opp[0].isupper() and ' ' not in opp else opp
        if len(allies) > 1:
            parts.append(sentence(f"{' and '.join(allies)} are allies who never strike each other; they face the {o}, "
                                  f"never each other, and every attack and block is aimed at the {o}"))
        else:
            parts.append(sentence(f"{allies[0]} faces the {o}; every attack and block is aimed at the {o}"))
    if sides.get("staging"):
        parts.append(sentence(f"Staging: {sides['staging']}"))
    if fighting and chars:
        # Wide moving fight shots measured 0.36-0.46 on faces (live 2026-11-06) - below the 0.50 line - while calm
        # medium shots of the same men measured 0.52-0.63. Give the model one clear face moment to lock identity on.
        parts.append(sentence(f"First second: {' and '.join(chars)} face the camera in a clear three-quarter view, faces sharp"))
    for c in sc.get("characters", []):
        if c.get("start"):
            pos = c.get("position")
            pos_txt = f", {pos} of the frame" if pos and pos.split()[0].lower() not in c["start"].lower() else ""
            parts.append(sentence(f"{c['name']} starts {c['start'].rstrip('.')}{pos_txt}"))
    beats = sc.get("beats") or []
    if not beats:
        raise Bad(f"scene {sc['id']}: no beats (the timed actions)")
    for b in beats:
        tgt = b.get("target")
        if tgt and b["who"] in allies and tgt in allies and b["who"] != tgt and not sc.get("allow_ally_conflict"):
            raise Bad(f"scene {sc['id']}: beat '{b['who']} -> {tgt}': allies would fight each other "
                      "(set allow_ally_conflict: true only if that is really wanted)")
        stem = (tgt or "").lower().rstrip("s")
        txt = f"{b['who']} {b['action'].rstrip('.')}" + (f", aimed at the {tgt.lower()}" if tgt and stem not in b["action"].lower() else "")
        parts.append(sentence(f"{float(b['from']):.1f}-{float(b['to']):.1f} s: {txt}"))
    loc = sc.get("location") or {}
    if loc.get("description"):
        parts.append(sentence(f"Place: {loc['description']}"))
    if sc.get("light"):
        parts.append(sentence(f"Light: {sc['light']}"))
    parts.append(sentence(f"Camera: {shot_d.get('camera_move', 'steady, slow follow')}"))
    for c in sc.get("characters", []):
        ident = cast[c["name"]].get("identity")
        if ident and len(ident.split()) > 30:
            raise Bad(f"scene {sc['id']}: identity too long for {c['name']} ({len(ident.split())} words, max 30) - "
                      f"keep the 30 most distinctive features (mole, glasses, hair, build)")
        parts.append(identity_line(base, cast, c["name"], words=30))
    lines = sc.get("dialogue") or []
    for d in lines:
        parts.append(f'{d["who"]} {"sings" if d.get("mode") == "sings" else "says"}: "{d["line"]}"')
    mode = (sb.get("audio") or {}).get("mode", "native")
    sound = "only quiet natural ambience" if mode == "soundtrack" else (sc.get("sound") or "")
    if chars and not lines:
        sound = (sound + ", " if sound else "") + "nobody talks"
    if sound:
        parts.append(sentence(f"Audio: {sound}"))
    parts += [FAST_REALISM, FAST_AVOID]
    prompt = " ".join(x for x in parts if x)
    if len(prompt) > FAST_MAX_CHARS:
        raise Bad(f"scene {sc['id']}: prompt too long ({len(prompt)} chars, max {FAST_MAX_CHARS}); long prompts make Flow "
                  f"drop details - shorten the identity, beats, place or staging text")
    refs = [cast[n].get("ref") or f"asset:{n}" for n in chars]
    if opp and cast[opp].get("ref"):
        refs.append(absolute(base, cast[opp]["ref"]))
    refs = [absolute(base, r) for r in refs][:3]
    v = {"type": "video", "prompt": prompt, "aspect_ratio": sb.get("aspect_ratio", "16:9"), "model": model,
         "reference_images": refs, "builder_lock": True, "scene_id": sc["id"], "parallel": True, "retries": 0,
         "variants": int(sc.get("video_variants", 1))}
    if model not in VEO:
        v["duration"], v["resolution"] = dur, res
    return v, prompt


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = {int(x) for x in args[i + 1].split(",")}
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        sys.exit(__doc__)
    sb_path = Path(args[0]).resolve()
    base = sb_path.parent
    sb = json.loads(sb_path.read_text(encoding="utf-8"))
    sb.setdefault("cast", {})
    out = base / "prompts"
    out.mkdir(exist_ok=True)
    errors, s1, s2, s3, plan, credits = validate(sb), [], [], [], [], 0
    sfast = []
    errors += check_looks(sb, base)
    for n, c in sb["cast"].items():
        if c.get("voice"):
            try:
                absolute(base, c["voice"])
            except Bad as e:
                errors.append(f"cast.{n}.voice: {e} (make it with voice_profile.py create)")
    st_file = ((sb.get("audio") or {}).get("soundtrack") or {}).get("file")
    if st_file:
        try:
            absolute(base, st_file)
        except Bad as e:
            errors.append(f"audio.soundtrack.file: {e}")
    aspect = sb.get("aspect_ratio", "16:9")
    for sc in sorted(sb["scenes"], key=lambda s: s["id"]):
        sid = f"scene-{sc['id']:02d}"
        if only is not None and sc["id"] not in only:
            continue
        try:
            for c in sc.get("characters", []):
                if c["name"] not in sb["cast"]:
                    raise Bad(f"{sid}: character {c['name']} not in cast")
                if kind(sb["cast"], c["name"]) == "extra":
                    raise Bad(f"{sid}: {c['name']} is an extra - reference it as sides.opponents, not as a character")
                if kind(sb["cast"], c["name"]) not in ("person", "character"):
                    raise Bad(f"{sid}: {c['name']} is a {kind(sb['cast'], c['name'])} - put it in 'subjects'")
            for s in sc.get("subjects", []):
                if s["name"] not in sb["cast"]:
                    raise Bad(f"{sid}: subject {s['name']} not in cast")
            shot = load_shot(sb, base, sc.get("ref_shot"), sc.get("ref_window"))
            model, dur, res = model_and_duration(sb, sc, shot)
            acc = sc.get("accepted") or {}

            # Likeness framing validation
            shot_d = sc.get("shot") or {}
            angle = (shot_d.get("angle") or (shot or {}).get("camera", {}).get("angle") or "").lower()
            size = (shot_d.get("size") or (shot or {}).get("shot_size") or "").lower()
            if sc.get("characters"):
                if any(p in angle for p in ("profile", "side view", "90 degree", "90-degree")) and not sc.get("allow_profile"):
                    raise Bad(f"{sid}: angle '{shot_d.get('angle')}' causes face resolution to drop <50px and distorts likeness/glasses into black smears; use 'three-quarter frontal' (or set allow_profile: true if intentional)")
                if not sc.get("allow_profile"):
                    texts = [str(c.get(k, "")) for c in sc["characters"] for k in ("start", "end", "expression")]
                    texts += [str(b.get("action", "")) for b in sc.get("beats", [])]
                    for txt in texts:
                        for m in re.finditer(r"\b(profile|side view|side-on|side on)\b", txt, re.I):
                            before = txt[max(0, m.start() - 16):m.start()].lower()
                            if "three-quarter" not in before and "3/4" not in before:
                                raise Bad(f"{sid}: '{txt[:60]}' puts a face in side profile - faces shrink and lose likeness; "
                                          "use 'three-quarter toward camera' (or set allow_profile: true)")
                if size in ("wide shot", "extreme wide shot", "long shot") and not sc.get("allow_wide"):
                    raise Bad(f"{sid}: shot size '{size}' is too wide for faces: it renders faces <50px where diffusion models cannot preserve facial likeness; use 'medium-wide shot', 'medium shot', or 'medium close-up' (or set allow_wide: true)")

            if sb.get("mode") == "fast":
                if acc.get("clip"):
                    plan.append(f"- {sid}: done (accepted clip {acc['clip']})")
                    continue
                v, fp = fast_scene(sb, base, sc, model, dur, res)
                check_words(sb, base, sc, fp, f"{sid} fast video")
                cost = (VEO[model] if model in VEO else OMNI_COST[res][dur]) * v["variants"]
                v["max_credits"] = int(sc.get("max_credits", cost))
                if v["max_credits"] < cost:
                    raise Bad(f"{sid}: max_credits {v['max_credits']} is below the expected {cost}")
                sfast.append(v)
                credits += cost
                (out / f"{sid}.md").write_text(f"# {sid} - {sc.get('title', '')}\n\nrefs: {v['reference_images']}\n\n{fp}\n",
                                               encoding="utf-8")
                continue
            md = [f"# {sid} - {sc.get('title', '')}", ""]
            refs, dropped = refs_for(sb, base, sc, "start", shot)
            p = keyframe_prompt(sb, base, sc, "start", shot, refs)
            check_words(sb, base, sc, p, f"{sid} start keyframe")
            if not acc.get("start"):  # finished work is never re-requested (no double work, no double spend)
                s1.append({"type": "image", "prompt": p, "aspect_ratio": aspect, "reference_images": refs,
                           "variants": int(sc.get("variants", 4)), "max_credits": 0})
            md += ["## START keyframe", f"refs: {refs}" + (f"  (dropped, max 3: {dropped})" if dropped else ""), "", p, ""]
            if sc.get("use_end_frame", True):
                if acc.get("start") and not acc.get("end"):
                    refs_e, dropped_e = refs_for(sb, base, sc, "end", shot)
                    pe = keyframe_prompt(sb, base, sc, "end", shot, refs_e)
                    check_words(sb, base, sc, pe, f"{sid} end keyframe")
                    s2.append({"type": "image", "prompt": pe, "aspect_ratio": aspect, "reference_images": refs_e,
                               "variants": int(sc.get("variants", 4)), "max_credits": 0})
                    md += ["## END keyframe", f"refs: {refs_e}" + (f"  (dropped: {dropped_e})" if dropped_e else ""), "", pe, ""]
                elif not acc.get("start"):
                    plan.append(f"- {sid}: END keyframe waits for an accepted START (storyboard accepted.start)")
            ready = acc.get("start") and (acc.get("end") or not sc.get("use_end_frame", True))
            has_end = bool(acc.get("end")) and sc.get("use_end_frame", True)
            mp = motion_prompt(sb, base, sc, shot, has_end=has_end)
            check_words(sb, base, sc, mp, f"{sid} motion")
            cost = VEO[model] if model in VEO else OMNI_COST[res][dur]
            md += [f"## VIDEO ({model}, {dur or 8} s, {res or 'fixed'}, ~{cost} credits)"
                   + (f", trim to reference {shot['duration']} s" if shot else ""), "", mp, ""]
            if acc.get("clip"):
                plan.append(f"- {sid}: done (accepted clip {acc['clip']})")
            elif ready:
                v = {"type": "video", "prompt": mp, "aspect_ratio": aspect, "model": model,
                     "first_frame": absolute(base, acc["start"]), "max_credits": int(sc.get("max_credits", cost))}
                if has_end:
                    v["last_frame"] = absolute(base, acc["end"])
                if model == OMNI:
                    v["duration"], v["resolution"] = dur, res
                if v["max_credits"] < cost:
                    raise Bad(f"{sid}: max_credits {v['max_credits']} is below the expected {cost}; the scene would be skipped")
                s3.append(v)
                credits += cost
            else:
                plan.append(f"- {sid}: video waits for accepted keyframes")
            (out / f"{sid}.md").write_text("\n".join(md), encoding="utf-8")
        except Bad as e:
            errors.append(str(e))
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{sid}: malformed field ({type(e).__name__}: {e}) - compare with references/storyboard-schema.md")
    project = sb.get("flow_project") or base.name
    files = {"stage1-start-keyframes.json": {"project": f"{project}-keyframes", "scenes": s1},
             "stage2-end-keyframes.json": {"project": f"{project}-keyframes", "scenes": s2},
             "stage3-video.json": {"project": project, "scenes": s3},
             "stage-fast-video.json": {"project": project, "scenes": sfast}}
    for name, payload in files.items():
        (out / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = [f"# Build plan for {project} (intent: {sb.get('intent', 'unspecified')}, {sb.get('style_mode', 'photoreal')})", "",
               f"- stage 1: {len(s1)} START keyframes (0 credits)", f"- stage 2: {len(s2)} END keyframes (0 credits)",
               f"- stage 3: {len(s3)} video scenes", f"- fast: {len(sfast)} video scenes in parallel batches",
               f"- expected credits: {credits}", ""] + plan
    if errors:
        summary += ["", "## ERRORS (fix storyboard.json and rebuild)"] + [f"- {e}" for e in errors]
    (out / "plan.md").write_text("\n".join(summary), encoding="utf-8")
    print(json.dumps({"mode": sb.get("mode", "precise"), "fast": len(sfast), "stage1": len(s1), "stage2": len(s2),
                      "stage3": len(s3), "stage3_credits": credits,
                      "waiting": plan, "errors": errors, "out": str(out)}, indent=2))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
