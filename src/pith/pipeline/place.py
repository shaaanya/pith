"""Shelf placement: which shelf a finished note belongs on.

A separate stage after the note is saved, so it can be re-run on stored notes without re-extracting.
Evidence: the user's own move (handled by the caller, never overwritten) > the model, reading the note,
the user's reason and the host against the CLOSED list of shelves > rules (the user's reason keywords,
a known host) > Reference when there is something to go on, else Other. Content type is deliberately
not a signal: a saved reel is already distilled, so "video" says nothing about what it is for."""
import re

from pith.providers.ports import ProviderError

# Ported verbatim from frontend/src/lib/shelves.ts (INTENT, HOSTS).
INTENT: list[tuple[str, re.Pattern]] = [
    ("try", re.compile(r"\b(try|install|test out|tool|repo|app|library|framework|plugin|extension|self-?host|set ?up)\b", re.I)),
    ("watch", re.compile(r"\b(watch|movie|film|show|series|documentary|episode|anime)\b", re.I)),
    ("listen", re.compile(r"\b(listen|podcast|album|song|playlist|music)\b", re.I)),
    ("read", re.compile(r"\b(read|book|essay|paper|newsletter)\b", re.I)),
    ("play", re.compile(r"\b(play|game|games)\b", re.I)),
    ("visit", re.compile(r"\b(visit|trip|travel|restaurant|cafe|hike|museum|hotel|go to)\b", re.I)),
]

HOSTS: dict[str, list[str]] = {
    "try": ["github.com", "gitlab.com", "npmjs.com", "pypi.org", "crates.io", "producthunt.com",
            "huggingface.co", "hub.docker.com"],
    "watch": ["letterboxd.com", "imdb.com", "themoviedb.org", "netflix.com", "justwatch.com"],
    "listen": ["open.spotify.com", "spotify.com", "bandcamp.com", "soundcloud.com",
               "music.apple.com", "podcasts.apple.com"],
    "read": ["goodreads.com", "thestorygraph.com"],
    "play": ["store.steampowered.com", "steampowered.com", "itch.io", "gog.com",
             "store.epicgames.com"],
    "visit": ["maps.app.goo.gl", "tripadvisor.com", "yelp.com", "airbnb.com", "booking.com"],
}

REASON_CAP = 100
BODY_CAP = 1500


def rules(intent: str | None, host: str | None, has_content: bool) -> tuple[str, str, str]:
    """(shelf, by, why) from the user's reason, then a known host; by is "rule" or "default"."""
    if intent:
        best = None
        for shelf, rx in INTENT:
            m = rx.search(intent)
            if m and (best is None or m.start() < best[1]):
                best = (shelf, m.start(), m.group(0))
        if best:
            return best[0], "rule", f"Your reason mentions “{best[2].lower()}”"
    h = (host or "").lower().removeprefix("www.")
    if h:
        for shelf, hosts in HOSTS.items():
            if x := next((x for x in hosts if h == x or h.endswith("." + x)), None):
                return shelf, "rule", f"Saved from {x}"
    if has_content or intent or h:
        return "reference", "default", "No action intent or known site, so kept as reference"
    return "other", "default", "Nothing to go on yet"


_SYSTEM = (
    "You file saved notes on a shelf. Pick the ONE shelf the note is most useful for, from this "
    "list only:\n{shelves}\n\nThe person's own reason for saving, when given, is the strongest "
    "evidence. Judge by what the person would do with the note, not by the kind of file it came "
    "from. If nothing fits, answer other.\n"
    "Answer on one line: <shelf id> | <why, at most 10 words>"
)


def build_prompt(title, body, intent, host, shelves, hint=None) -> list[dict]:
    lines = "\n".join(f"{s['id']}: {s['name']} - {s['blurb']}".rstrip(" -") for s in shelves)
    parts = []
    if intent:
        parts.append(f"The person's reason for saving: {intent.strip()}")
    if host:
        parts.append(f"Saved from: {host}")
    if hint:
        parts.append(f"A simple rule suggests: {hint}")
    parts.append(f"Note title: {title or '(none)'}\nNote:\n{(body or '')[:BODY_CAP]}")
    return [{"role": "system", "content": _SYSTEM.format(shelves=lines)},
            {"role": "user", "content": "\n".join(parts)}]


def parse(text: str, shelves) -> tuple[str, str] | None:
    """(shelf id, reason) from the model's answer. Shelf ids and names both match; the first one
    named wins and, at the same spot, the longest ("read-later" beats "read"). Anything else is None.
    The reason is cut to REASON_CAP characters."""
    head, _, why = (text or "").partition("|")
    best = None  # (start, -length, id)
    for s in shelves:
        for key in {s["id"], s.get("name") or s["id"]}:
            m = re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", head, re.I)
            if m and (best is None or (m.start(), -len(key)) < best[:2]):
                best = (m.start(), -len(key), s["id"])
    return (best[2], why.strip()[:REASON_CAP]) if best else None


def ask(backend, title, body, intent, host, shelves, hint=None) -> tuple[str, str, str] | None:
    """(shelf id, reason, "backend:model") or None when the call fails or the answer is not a shelf."""
    try:
        res = backend.generate(build_prompt(title, body, intent, host, shelves, hint),
                               max_tokens=40)
    except ProviderError:
        return None
    got = parse(res.text, shelves)
    return (*got, f"{res.backend}:{res.model}") if got else None


def decide(backend, title, body, intent, host, shelves) -> tuple[str, str, str, str | None]:
    """(shelf, by, why, model). The model reads the note, the user's reason and the host; when there
    is no model backend, the call fails or the answer is not a shelf, the rules decide.

    Benchmark (eval/notes, gemma4:e4b, 36 notes): model 94%, rules 81%; adding the rule's suggestion
    to the prompt, or letting a rule override the model's "other", scored the same, so neither is used."""
    if backend is not None:
        got = ask(backend, title, body, intent, host, shelves)
        if got:
            shelf, why, model = got
            return shelf, "model", why or "Chosen from the note's content", model
    shelf, by, why = rules(intent, host, bool((body or "").strip()))
    return shelf, by, why, None
