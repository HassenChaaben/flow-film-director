"""Local pre-scan that mirrors the public Agensi security checks (https://www.agensi.io/security).

Agensi does not publish its exact rules, so this is stricter than needed: it fails on every pattern their
review e-mail flagged and every trigger their docs list. Run it on the skill folder or the zip before uploading.

Usage:
  python tools/agensi_prescan.py skills/flow-film-director --edition community
  python tools/agensi_prescan.py path/to/flow-film-director.zip            (Pro, the default)
The Community edition keeps 6 small stub scripts that link to the Pro listing; the Pro edition must not.
Exit 0 = clean, 1 = findings (printed one per line).
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# Words that the scanner matches as plain substrings (case-insensitive).
FORBIDDEN = {
    "curl": "shell download tool name (also matches words that contain it)",
    "wget": "shell download tool name",
    "settimeout": "timer pattern flagged as dangerous code",
    "os.environ": "environment variable read",
    "getenv": "environment variable read",
    "process.env": "environment variable read",
    "eval(": "dynamic code execution",
    "exec(": "dynamic code execution",
    "shell=true": "shell command execution",
    "os.system": "shell command execution",
    "child_process": "shell command execution",
    "rm -rf": "destructive file operation",
    "chmod 777": "unsafe permissions",
    "sudo": "privilege escalation",
    "base64": "encoded content",
    "ignore previous": "prompt injection phrase",
    "do not tell the user": "prompt injection phrase",
    "secretly": "prompt injection phrase",
    "elevenlabs": "cloud upload of local audio (removed engine)",
    "pytorch.org": "undeclared download host",
    "videodb.io": "cloud upload of local video",
    "[pro feature]": "Community stub inside the Pro package",
}
# Only these files may contain URLs, and only to these hosts.
URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)", re.I)
URL_ALLOWED = {
    "scripts/setup_env.py": {"github.com", "storage.googleapis.com"},
    "scripts/engines/voicebox_engine.py": {"127.0.0.1"},
}
BLOCKED_EXT = {".exe", ".dll", ".so", ".dylib", ".bin", ".app", ".dmg", ".msi", ".deb", ".rpm", ".wasm",
               ".class", ".jar", ".war", ".pyc", ".onnx", ".task", ".zip"}
TEXT_EXT = {".md", ".py", ".mjs", ".js", ".ts", ".json", ".txt", ".patch", ".yaml", ".yml", ".toml"}


def read_files(target: Path) -> dict[str, bytes]:
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as z:
            return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    return {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}


STUBS = {f"scripts/{n}.py" for n in ("fast_review", "identity_check", "motion_match", "object_check",
                                      "voice_convert", "voice_profile")}


def scan(target: Path, edition: str = "pro") -> list[str]:
    files = read_files(target)
    out: list[str] = []
    if "SKILL.md" not in files:
        out.append("SKILL.md: missing at the root")
    else:
        head = files["SKILL.md"].decode("utf-8", "replace")
        m = re.match(r"---\r?\n(.*?)\r?\n---", head, re.S)
        if not m or not re.search(r"^name:\s*flow-film-director\s*$", m.group(1), re.M) \
                or not re.search(r"^description:\s*\S", m.group(1), re.M):
            out.append("SKILL.md: frontmatter needs name: flow-film-director and a description")
    if len(files) > 1000:
        out.append(f"package: {len(files)} files (limit 1000)")
    for name, data in sorted(files.items()):
        ext = Path(name).suffix.lower()
        if ext in BLOCKED_EXT or "__pycache__" in name or "/." in "/" + name:
            out.append(f"{name}: file type not allowed in the package")
            continue
        if ext not in TEXT_EXT:
            out.append(f"{name}: not a text file")
            continue
        text = data.decode("utf-8", "replace")
        low = text.lower()
        stub = edition == "community" and name in STUBS
        for word, why in FORBIDDEN.items():
            if stub and word == "[pro feature]":
                continue
            if word in low:
                line = low[:low.index(word)].count("\n") + 1
                out.append(f"{name}:{line}: '{word}' - {why}")
        allowed = URL_ALLOWED.get(name, set()) | ({"www.agensi.io"} if stub else set())
        for m in URL_RE.finditer(text):
            if m.group(1).lower() not in allowed:
                line = text[:m.start()].count("\n") + 1
                out.append(f"{name}:{line}: URL to {m.group(1)} - network access outside the declared setup files")
    return out


def main() -> int:
    args = sys.argv[1:]
    edition = "pro"
    if "--edition" in args:
        i = args.index("--edition")
        edition = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or edition not in ("pro", "community"):
        print(__doc__)
        return 2
    findings = scan(Path(args[0]), edition)
    for f in findings:
        print(f)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
