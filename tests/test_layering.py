import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "infoparser"
LAYERS = ["domain", "pipeline", "inbox", "retrieval"]
BACKENDS = {"heuristic", "openai_compat", "cli_backend", "anthropic", "tesseract", "whisper_cpp"}


def _bad_imports(path):
    bad = []
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""]
            if n.module == "infoparser.providers":
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
