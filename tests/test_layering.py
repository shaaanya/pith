import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "infoparser"
LAYERS = ["domain", "pipeline", "inbox", "retrieval"]
BACKENDS = {"heuristic", "openai_compat", "cli_backend", "anthropic", "tesseract", "whisper_cpp"}


def _bad_imports(path, root=SRC):
    bad = []
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:  # relative import: resolve against this file's package
                pkg = ["infoparser", *path.relative_to(root).parts[:-1]]
                pkg = pkg[: len(pkg) - (n.level - 1)]
                base = ".".join([*pkg, *([n.module] if n.module else [])])
            mods = [base]
            if base == "infoparser.providers":
                mods += [f"infoparser.providers.{a.name}" for a in n.names]
        else:
            continue
        bad += [m for m in mods if m.startswith("infoparser.providers.") and m.split(".")[2] in BACKENDS]
    return bad


def test_domain_layers_do_not_import_backends():
    offenders = {
        str(p): b for layer in LAYERS if (SRC / layer).is_dir()
        for p in (SRC / layer).rglob("*.py") if (b := _bad_imports(p))
    }
    assert not offenders


def test_scanner_flags_bad_imports(tmp_path):
    pkg = tmp_path / "domain"
    pkg.mkdir()
    cases = {
        "a.py": "import infoparser.providers.heuristic",
        "b.py": "from infoparser.providers import openai_compat",
        "c.py": "from ..providers.anthropic import X",
        "d.py": "from infoparser.providers.ports import P",
    }
    for name, src in cases.items():
        (pkg / name).write_text(src)
    flagged = {n for n in cases if _bad_imports(pkg / n, tmp_path)}
    assert flagged == {"a.py", "b.py", "c.py"}
