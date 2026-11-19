"""Placement: rules (ported from the UI), prompt, answer parsing and the model call."""
from pith.pipeline import place
from pith.providers.ports import GenResult, ProviderError
from pith.store.shelves import list_shelves

IDS = ["watch", "listen", "read", "play", "try", "visit", "reference", "other"]
SHELVES = [{"id": i, "name": i.title(), "blurb": f"about {i}"} for i in IDS]


class Fake:
    name, locality = "f", "local"

    def __init__(self, reply=None, boom=False):
        self.reply, self.boom, self.calls = reply, boom, []

    def generate(self, messages, *, json_schema=None, max_tokens=None):
        self.calls.append(messages)
        if self.boom:
            raise ProviderError("down")
        return GenResult(self.reply, "m", "f")


def test_rules_reason_beats_site_and_earliest_keyword_wins():
    assert place.rules("try this tool", None, True)[:2] == ("try", "rule")
    assert place.rules("read later", "github.com", True)[0] == "read"
    assert place.rules("a film to watch and a book to read", None, True)[0] == "watch"
    shelf, by, why = place.rules(None, "github.com", True)
    assert (shelf, by) == ("try", "rule") and "github.com" in why
    assert place.rules(None, "www.letterboxd.com", True)[0] == "watch"


def test_rules_fall_back_to_reference_then_other():
    assert place.rules(None, "example.com", True)[:2] == ("reference", "default")
    assert place.rules(None, None, False)[:2] == ("other", "default")


def test_parse_is_lenient_and_closed():
    assert place.parse("try | a repo to try", SHELVES) == ("try", "a repo to try")
    assert place.parse("Answer: WATCH", SHELVES) == ("watch", "")
    assert place.parse("reference and other", SHELVES) == ("reference", "")
    assert place.parse("I think trying it", SHELVES) is None
    assert place.parse("", SHELVES) is None
    assert place.parse("read | " + "x" * 300, SHELVES)[1] == "x" * 100


def test_prompt_lists_every_shelf_and_leads_with_the_reason():
    msgs = place.build_prompt("T", "body text", "for the road trip", "example.com", SHELVES,
                              hint="try")
    text = "\n".join(m["content"] for m in msgs)
    assert all(i in text for i in IDS) and "for the road trip" in text and "example.com" in text
    assert "body text" in text and "try" in text


def test_ask_returns_choice_or_none_never_raises():
    got = place.ask(Fake("listen | a playlist"), "T", "b", None, None, SHELVES)
    assert got == ("listen", "a playlist", "f:m")
    assert place.ask(Fake("no idea"), "T", "b", None, None, SHELVES) is None
    assert place.ask(Fake(boom=True), "T", "b", None, None, SHELVES) is None


def test_builtin_ids_match_the_seeded_shelves(svc):
    assert [s["id"] for s in list_shelves(svc.conn)] == IDS


def test_decide_model_then_rules():
    got = place.decide(Fake("try | a repo"), "T", "b", None, "example.com", SHELVES)
    assert got == ("try", "model", "a repo", "f:m")
    assert place.decide(Fake("listen"), "T", "b", None, None, SHELVES)[2] == \
        "Chosen from the note's content"
    for backend in (None, Fake("no idea"), Fake(boom=True)):
        shelf, by, _, model = place.decide(backend, "T", "b", "try this", None, SHELVES)
        assert (shelf, by, model) == ("try", "rule", None)
    assert place.decide(None, "T", "", None, None, SHELVES)[:2] == ("other", "default")


def test_parse_handles_custom_shelves_that_start_like_builtins_and_names():
    custom = [*SHELVES, {"id": "read-later", "name": "Read later", "blurb": ""},
              {"id": "recipes-to-cook", "name": "Recipes to cook", "blurb": ""}]
    assert place.parse("read-later | x", custom)[0] == "read-later"
    assert place.parse("read | x", custom)[0] == "read"
    assert place.parse("Recipes to cook", custom)[0] == "recipes-to-cook"
    assert place.parse("Read later", custom)[0] == "read-later"
