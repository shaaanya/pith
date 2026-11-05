"""JSON schemas for distillation profiles and a tiny validator.

Supports type/properties/required/items/minLength; minLength counts characters after strip(), so
empty and whitespace-only text is invalid (such output goes to repair, then the next backend).
"""
_STR = {"type": "string"}
_NES = {"type": "string", "minLength": 1}  # non-empty after strip
_STRS = {"type": "array", "items": _STR}
_NES_LIST = {"type": "array", "items": _NES}
_INSIGHT = {"type": "object", "required": ["text"], "properties": {"text": _NES, "quote": _STR}}


def _profile(extra: dict | None = None) -> dict:
    props = {"summary": _NES, "insights": {"type": "array", "items": _INSIGHT},
             "topics": _STRS, "entities": _STRS, **(extra or {})}
    return {"type": "object", "required": ["summary"], "properties": props}


SCHEMAS: dict[str, dict] = {
    "generic": _profile(),
    "article": _profile({"key_points": _NES_LIST}),
    "programming": _profile({"snippets": {"type": "array", "items": {
        "type": "object", "required": ["title", "code"],
        "properties": {"title": _NES, "code": _NES, "quote": _STR}}}}),
    "paper": _profile({"claims": {"type": "array", "items": _INSIGHT}}),
    "collection": {"type": "object", "required": ["title", "entries"], "properties": {
        "title": _NES, "summary": _STR, "topics": _STRS, "entities": _STRS,
        "entries": {"type": "array", "items": {
            "type": "object", "required": ["name"],
            "properties": {"name": _NES, "note": _STR, "quote": _STR}}}}},
}

_TYPES = {"object": dict, "array": list, "string": str, "number": (int, float)}


def validate(obj, schema: dict, path: str = "$") -> str | None:
    """Return an error string, or None if valid."""
    t = schema.get("type")
    if t and not isinstance(obj, _TYPES[t]) or isinstance(obj, bool) and t == "number":
        return f"{path}: expected {t}"
    if t == "string" and len(obj.strip()) < schema.get("minLength", 0):
        return f"{path}: must not be empty"
    if t == "object":
        for k in schema.get("required", []):
            if k not in obj:
                return f"{path}: missing '{k}'"
        for k, sub in schema.get("properties", {}).items():
            if k in obj and (e := validate(obj[k], sub, f"{path}.{k}")):
                return e
    elif t == "array":
        for i, x in enumerate(obj):
            if e := validate(x, schema.get("items", {}), f"{path}[{i}]"):
                return e
    return None


def profile_for(content_type: str, hints: str) -> str:
    """Distillation profile for a content type and the user's hints."""
    h = (hints or "").lower()
    if any(w in h for w in ("top ", "list of", "collection", "best ")):
        return "collection"
    if any(w in h for w in ("code", "programming", "python", "api ")):
        return "programming"
    if "paper" in h or "arxiv" in h:
        return "paper"
    if content_type in ("web", "article"):
        return "article"
    return "generic"
