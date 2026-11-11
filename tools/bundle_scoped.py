"""Bundle one entry script and every sibling module it imports into ONE self-contained .py file.

Agensi runs each skill script alone from a temporary file, so a script cannot import the other files of the skill.
Each imported module is wrapped in its own function (its names stay private, so two modules may define the same
function name) and is loaded lazily on first use, exactly like a normal import. No exec/eval, no code is downloaded.

    python tools/bundle_scoped.py --root skills/flow-film-director/scripts --extra-root ../flow-film-director-pro/scripts \
        --entry cast_check.py --out dist/cast_check.py --title "Pick the best cast photo"
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from pathlib import Path

HELPERS = '''
import types as _bundle_types


class _LazyModule:
    """Stands in for a bundled module: loads it on first attribute access, like `import` would."""
    __slots__ = ("_bundle_name", "_bundle_load", "_bundle_mod")

    def __init__(self, name, load):
        object.__setattr__(self, "_bundle_name", name)
        object.__setattr__(self, "_bundle_load", load)
        object.__setattr__(self, "_bundle_mod", None)

    def _bundle_get(self):
        mod = object.__getattribute__(self, "_bundle_mod")
        if mod is None:
            object.__setattr__(self, "_bundle_mod", False)
            try:
                mod = _bundle_types.SimpleNamespace(**object.__getattribute__(self, "_bundle_load")())
            except BaseException:
                object.__setattr__(self, "_bundle_mod", None)
                raise
            object.__setattr__(self, "_bundle_mod", mod)
        elif mod is False:
            raise ImportError("circular import of " + object.__getattribute__(self, "_bundle_name"))
        return mod

    def __getattr__(self, key):
        return getattr(self._bundle_get(), key)

    def __setattr__(self, key, value):
        setattr(self._bundle_get(), key, value)
'''


class Bundler:
    def __init__(self, roots: list[Path]):
        self.roots = roots
        self.files: dict[str, Path] = {}          # dotted module name -> file
        self.packages: set[str] = set()
        for root in roots:
            for f in root.rglob("*.py"):
                if "__pycache__" in f.parts:
                    continue
                rel = f.relative_to(root).with_suffix("")
                parts = list(rel.parts)
                if parts[-1] == "__init__":
                    continue
                name = ".".join(parts)
                if name not in self.files:            # first root wins (the Pro copy is passed first)
                    self.files[name] = f
                if len(parts) > 1:
                    self.packages.add(parts[0])

    def internal(self, dotted: str | None) -> bool:
        return bool(dotted) and (dotted in self.files or dotted.split(".")[0] in self.packages)

    def deps(self, tree: ast.AST) -> set[str]:
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out |= {a.name for a in node.names if a.name in self.files}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and self.internal(node.module):
                if node.module in self.files:
                    out.add(node.module)
                for a in node.names:
                    if f"{node.module}.{a.name}" in self.files:
                        out.add(f"{node.module}.{a.name}")
        return out

    def closure(self, entry: str) -> list[str]:
        seen, todo = [], [entry]
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.append(m)
            todo += sorted(self.deps(ast.parse(self.files[m].read_text(encoding="utf-8"))))
        return seen

    # ---- source rewriting -------------------------------------------------------------------------
    def rewrite(self, src: str, wrapped: bool) -> tuple[str, str | None]:
        """Rewrite internal imports (and `global` -> `nonlocal` for wrapped modules). Returns (code, docstring)."""
        tree = ast.parse(src)
        lines = src.splitlines()
        edits: list[tuple[int, int, str]] = []   # (first line, last line, replacement for the first line), 1-based
        doc = None
        body = tree.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            doc = "\n".join(lines[body[0].lineno - 1: body[0].end_lineno or body[0].lineno])
            edits.append((body[0].lineno, body[0].end_lineno or body[0].lineno, ""))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                edits.append((node.lineno, node.end_lineno or node.lineno, ""))
            elif isinstance(node, ast.Import) and any(self.internal(a.name) for a in node.names):
                ext = [a for a in node.names if not self.internal(a.name)]
                parts = []
                if ext:
                    parts.append("import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in ext))
                for a in node.names:
                    if self.internal(a.name) and a.asname:
                        parts.append(f"{a.asname} = {a.name}")
                edits.append((node.lineno, node.end_lineno or node.lineno, "; ".join(parts) or "pass"))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and self.internal(node.module):
                if any(a.name == "*" for a in node.names):
                    raise SystemExit(f"star import from {node.module} is not supported")
                parts = [f"{a.asname or a.name} = {node.module}.{a.name}" for a in node.names]
                edits.append((node.lineno, node.end_lineno or node.lineno, "; ".join(parts)))
            elif isinstance(node, ast.ImportFrom) and node.level > 0:
                raise SystemExit("relative imports are not supported")
        if wrapped:
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.Global):
                        if node is tree:
                            edits.append((child.lineno, child.end_lineno or child.lineno, ""))
                        else:
                            ln = lines[child.lineno - 1]
                            c = child.col_offset
                            lines[child.lineno - 1] = ln[:c] + "nonlocal" + ln[c + len("global"):]
        for first, last, new in sorted(edits, reverse=True):
            indent = lines[first - 1][: len(lines[first - 1]) - len(lines[first - 1].lstrip())]
            lines[first - 1: last] = [indent + new if new else ""] + [""] * (last - first)
        code = "\n".join(lines) + "\n"
        ast.parse(code)                         # the rewrite must still be valid Python
        return code, doc

    @staticmethod
    def string_rows(code: str) -> set[int]:
        """Rows (1-based) that sit inside a multi-line string after its first row: they must not be re-indented."""
        rows, stack = set(), []
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            name = tokenize.tok_name[tok.type]
            if name == "FSTRING_START":
                stack.append(tok.start[0])
            elif name == "FSTRING_END":
                start = stack.pop()
                if not stack:
                    rows.update(range(start + 1, tok.end[0] + 1))
            elif tok.type == tokenize.STRING and tok.end[0] > tok.start[0] and not stack:
                rows.update(range(tok.start[0] + 1, tok.end[0] + 1))
        return rows

    def wrap(self, name: str) -> str:
        code, _ = self.rewrite(self.files[name].read_text(encoding="utf-8"), wrapped=True)
        keep = self.string_rows(code)
        fn = "_load_" + name.replace(".", "_")
        out = [f"def {fn}():", f"    __name__ = {name!r}"]
        for i, line in enumerate(code.splitlines(), 1):
            out.append(line if (i in keep or not line.strip()) else "    " + line)
        out.append("    return dict(locals())")
        return "\n".join(out) + "\n"

    def build(self, entry: str, title: str) -> str:
        mods = self.closure(entry)
        libs = sorted(m for m in mods if m != entry)
        entry_code, doc = self.rewrite(self.files[entry].read_text(encoding="utf-8"), wrapped=False)
        parts = [f"# {title}", "# One self-contained file: the modules it needs are bundled below (generated, do not edit).",
                 doc or '"""' + title + '"""', "from __future__ import annotations", HELPERS]
        for m in libs:
            parts.append(self.wrap(m))
        top = sorted({m for m in libs if "." not in m})
        for m in top:
            parts.append(f"{m} = _LazyModule({m!r}, _load_{m})")
        for pkg in sorted({m.split(".")[0] for m in libs if "." in m}):
            subs = sorted(m for m in libs if m.startswith(pkg + "."))
            inner = ", ".join(f"{s.split('.', 1)[1]}=_LazyModule({s!r}, _load_{s.replace('.', '_')})" for s in subs)
            parts.append(f"{pkg} = _bundle_types.SimpleNamespace({inner})")
        parts.append("# ---- " + entry + " " + "-" * 60)
        parts.append(entry_code)
        out = "\n\n".join(p.strip("\n") + "\n" for p in parts)
        ast.parse(out)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", action="append", required=True, type=Path, help="script folder(s); the first one wins")
    ap.add_argument("--entry", required=True, help="entry script file name, e.g. cast_check.py")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--title", required=True)
    a = ap.parse_args()
    b = Bundler(a.root)
    entry = a.entry[:-3] if a.entry.endswith(".py") else a.entry
    if entry not in b.files:
        print(f"{a.entry} not found in {a.root}")
        return 1
    code = b.build(entry, a.title)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(code, encoding="utf-8", newline="\n")
    print(f"{a.out.name}: {len(code.encode()) // 1024} KB, modules: {', '.join(b.closure(entry))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
