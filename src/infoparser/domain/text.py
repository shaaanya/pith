"""Text normalisation helpers."""
import re


def normalize(name) -> str:
    """Casefold, trim, collapse whitespace. Accepts {"name": ...}; anything else is str()-ed."""
    if isinstance(name, dict):
        name = name.get("name", "")
    return re.sub(r"\s+", " ", str(name)).strip().casefold()
