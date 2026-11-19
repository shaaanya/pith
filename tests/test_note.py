"""Knowledge-note pipeline: deterministic parts (repair, verify, compose, mentions) and build()."""
import json

from pith.domain.models import SegmentIn
from pith.pipeline import note
from pith.pipeline.runner import intent_of
from pith.providers.heuristic import HeuristicBackend
from pith.providers.ports import Capabilities, GenResult, ProviderError
from pith.providers.registry import Registry

DESC = ("Prep plan: learn idempotency and DynamoDB. Read Marc Brooker. Practice on Devmaxx. "
        "Chapter 7 of Designing Data-Intensive Applications.")
TRANSCRIPT = ("learn item potency and dynamo db then read mark brooker and practice on dev max "
              "chapter seven of designing data intensive applications")
SEGS = [SegmentIn(0, DESC, "description"), SegmentIn(1, TRANSCRIPT, "t=0-30")]


class Fake:
    locality, type = "local", "fake"

    def __init__(self, replies):
        self.name, self.replies, self.calls = "f", list(replies), []
        self.capabilities = Capabilities(text=True, context_window=8192)

    def generate(self, messages, *, json_schema=None, max_tokens=None):
        self.calls.append(messages)
        return GenResult(json.dumps(self.replies.pop(0)), "m", "f")


def reg(fake):
    h = HeuristicBackend()
    h.type = "heuristic"
    return Registry({"f": fake, "heuristic": h}, {}, {"distill": ["f"]}, False)


def test_repair_terms_fixes_mishearings_from_the_description():
    out, repairs = note.repair_terms(SEGS)
    fixed = out[1].text
    assert "idempotency" in fixed and "DynamoDB" in fixed and "Devmaxx" in fixed
    assert "Marc" in fixed and "mark" not in fixed and "item potency" not in fixed
    assert "learn idempotency and" in fixed  # neighbouring words are never rewritten
    assert SEGS[1].text == TRANSCRIPT  # stored evidence is untouched
    assert ("item potency", "idempotency") in repairs


def test_repair_terms_does_nothing_without_a_description():
    out, repairs = note.repair_terms([SegmentIn(0, TRANSCRIPT, "t=0-30")])
    assert out[0].text == TRANSCRIPT and repairs == []


def test_verify_drops_unsupported_and_commentary_and_promo_and_duplicates():
    units = [
        {"type": "fact", "text": "Salary is $999K"},  # number not in the source
        {"type": "fact", "text": "Quantum computers solve payments"},  # words not in the source
        {"type": "fact", "text": "The creator provides an actionable roadmap for preparing"},
        {"type": "step", "text": "Comment GUIDE for the full guide"},
        {"type": "step", "text": "Practice on Devmaxx"},
        {"type": "step", "text": "Practice on Devmaxx."},  # duplicate
    ]
    segs = [*SEGS, SegmentIn(2, "Comment GUIDE for the full guide", "t=30-40")]
    kept, dropped = note.verify(units, segs)
    assert [u["text"] for u in kept] == ["Practice on Devmaxx"]
    assert kept[0]["segment_idx"] in (0, 1) and kept[0]["support"] == 1.0
    assert dropped.keys() >= {"unsupported_number", "unsupported_text", "meta_commentary",
                              "promo", "duplicate"}


def test_verify_accepts_a_number_the_source_wrote_as_a_word():
    segs = [SegmentIn(0, "there are twelve steps and 1,500 users", "t=0-5")]
    kept, dropped = note.verify([{"type": "fact", "text": "12 steps for 1500 users"},
                                 {"type": "fact", "text": "13 steps for 1500 users"}], segs)
    assert [u["text"] for u in kept] == ["12 steps for 1500 users"]
    assert dropped == {"unsupported_number": 1}


def test_compose_layout_follows_the_units():
    steps = [{"type": "step", "text": "A first"}, {"type": "step", "text": "B second"}]
    assert note.compose("Ctx.", steps, None, [], []) == "Ctx.\n\n1. A first\n2. B second"
    mixed = [{"type": t, "text": t.title() + " x"} for t in ("step", "fact", "claim", "fact",
                                                           "warning")]
    md = note.compose("", mixed, None, ["Only 4 of 10 given"], ["No visuals"])
    assert "## Steps" in md and "## Facts" in md and "## Definitions" not in md
    assert md.endswith("**Limits:** Only 4 of 10 given. No visuals.")
    md = note.compose("", mixed, "Saved for the claim", [], [])
    assert md.startswith("**Why saved:** Saved for the claim\n\n## Relevant to why you saved")


def test_mentions_keep_brief_names_and_drop_invented_entities():
    src = ("there is a skill called systematic-debugging. "
           "Marcus likes Four Thousand Weeks by Oliver Burkeman.")
    names = note.mentions(src, ["Marcus", "Totally Invented Corp"])
    assert {"systematic-debugging", "Four Thousand Weeks", "Oliver Burkeman", "Marcus"} <= set(names)
    assert "Totally Invented Corp" not in names


REPLY = {"context": "A creator shares an interview prep plan.",
         "units": [{"type": "step", "text": "learn idempotency and DynamoDB"},
                   {"type": "resource", "text": "Marc Brooker's blog"},
                   {"type": "fact", "text": "The video explains idempotency"}],
         "entities": ["Devmaxx", "Invented Corp"], "gaps": []}


def test_build_returns_note_mentions_and_units_with_stats():
    fake = Fake([REPLY])
    cands, by = note.build(reg(fake), SEGS, title="Prep", intent=None, limits=["Visuals not read"])
    kinds = [c.kind for c in cands]
    assert kinds[:2] == ["note", "mentions"] and kinds.count("unit") == 2
    n = cands[0]
    assert "1. Learn idempotency and DynamoDB" not in n.body  # two types: sectioned or bulleted
    assert "Learn idempotency and DynamoDB" in n.body and "The video" not in n.body
    assert n.body.endswith("Visuals not read.")
    assert n.data["intent"] == {"state": "unknown", "text": None}
    assert n.data["dropped"] == {"meta_commentary": 1} and n.data["stats"]["calls"] == 1
    assert "Invented Corp" not in cands[1].body and "Devmaxx" in cands[1].body
    assert by == "f:m"
    assert "DynamoDB" in fake.calls[0][1]["content"]  # the model read the repaired transcript
    assert any(r["term"] == "idempotency" for r in n.data["repairs"])
    assert n.data["scope"] == "full"


def test_build_with_intent_runs_a_focus_pass_when_nothing_matches():
    segs = [SegmentIn(0, "intro chat about weather and cats", "t=0-5"),
            SegmentIn(1, "the tool called pgbouncer pools connections for postgres", "t=5-9")]
    first = {"context": "", "units": [{"type": "fact", "text": "They chat about weather and cats"}],
             "entities": [], "gaps": []}
    focus = {"context": "", "units": [{"type": "resource", "text": "pgbouncer pools connections"}],
             "entities": [], "gaps": []}
    fake = Fake([first, focus])
    cands, _ = note.build(reg(fake), segs, title="", intent="the connection pooling tool")
    assert len(fake.calls) == 2
    assert cands[0].data["intent"]["state"] == "explicit"
    assert "## Relevant to why you saved this" in cands[0].body
    assert any(u["focus"] for u in cands[0].data["units"])


def test_build_flags_intent_that_matches_nothing():
    segs = [SegmentIn(0, "intro chat about weather and cats today", "t=0-5"),
            SegmentIn(1, "more words about the dog", "t=5-9")]
    reply = {"context": "", "units": [{"type": "fact", "text": "Chat about weather and cats"}],
             "entities": [], "gaps": []}
    none = {"context": "", "units": [], "entities": [], "gaps": []}
    cands, _ = note.build(reg(Fake([reply, none])), segs, intent="kubernetes operators")
    assert any("Nothing in the source matched" in x for x in cands[0].data["limits"])
    assert cands[0].data["scope"] == "unscoped" and "Chat about weather and cats" in cands[0].body


def test_short_plain_note_is_kept_verbatim_without_a_model_call():
    fake = Fake([])
    text = "Dentist Thu 3pm, bring insurance card."
    cands, by = note.build(reg(fake), [SegmentIn(0, text, "char=0-38")], kind="note")
    assert cands[0].body == text and fake.calls == [] and by == "verbatim"


def test_build_without_a_model_backend_returns_none():
    h = HeuristicBackend()
    h.type = "heuristic"
    assert note.build(Registry({"h": h}, {}, {"distill": []}, False), SEGS) is None


def test_intent_is_the_users_words_not_adapter_provenance():
    assert intent_of({"user_context": "for the DORA metrics", "adapter": "cli"}) == \
        "for the DORA metrics"
    assert intent_of({"user_context": "from notes.txt", "adapter": "fs"}) is None
    assert intent_of({"user_context": None, "adapter": "dashboard"}) is None


def test_long_source_maps_over_batches_keeping_units_not_summaries():
    segs = [SegmentIn(0, "Description: tools named alpha-tool and beta-tool.", "description"),
            *[SegmentIn(i, f"section {i} says the alpha-tool setting number {i}0 matters " * 12,
                        f"char={i}") for i in range(1, 7)]]
    fake = Fake([{"context": "Long talk.", "gaps": [], "entities": [],
                  "units": [{"type": "fact", "text": f"alpha-tool setting number {i}0 matters"}]}
                 for i in range(1, 41)])
    fake.capabilities = Capabilities(text=True, context_window=1000)  # forces several batches
    cands, _ = note.build(reg(fake), segs, title="Talk")
    assert len(fake.calls) > 1
    assert cands[0].data["stats"]["calls"] == len(fake.calls)
    assert len({u["text"] for u in cands[0].data["units"]}) == len(cands[0].data["units"])
    assert all("Description:" in c[1]["content"] for c in fake.calls)  # every batch keeps context


def test_despeak_turns_dictated_code_into_symbols_but_leaves_prose():
    dictated = ("build it with docker build dash t app dot. run docker run dash p 80 colon 8000 "
                "dash dash env dot env and reverse underscore proxy")
    out = note.despeak(dictated)
    assert "-t app ." in out and "-p 80:8000" in out and "--env .env" in out
    assert "reverse_proxy" in out
    prose = "a dash of salt and a polka dot dress"
    assert note.despeak(prose) == prose


def test_fuzzy_repair_never_splits_a_word_or_rewrites_common_words():
    segs = [SegmentIn(0, "Deploy a Flask app on a VPS. Docker in 10 minutes.", "description"),
            SegmentIn(1, "docker run it now and build flaskapp", "t=0-5")]
    out, repairs = note.repair_terms(segs)
    assert out[1].text == segs[1].text and repairs == []


def test_a_correction_retires_the_value_it_corrects():
    units = [{"type": "fact", "text": "The cluster had 6 nodes"},
             {"type": "fact", "text": "The original cluster actually had 8 nodes, not 6"},
             {"type": "fact", "text": "The cluster moved to 12 nodes"}]
    segs = [SegmentIn(0, "cluster had 6 nodes. correction it actually had 8 nodes not 6. "
                         "then moved to 12 nodes", "t=0-9")]
    kept, dropped = note.verify(units, segs)
    assert [u["text"] for u in kept] == ["The original cluster actually had 8 nodes, not 6",
                                         "The cluster moved to 12 nodes"]
    assert dropped == {"superseded_by_correction": 1}


def test_config_text_is_kept_verbatim_in_a_code_block():
    conf = "limit_req_zone $addr zone=api:10m rate=5r/s;\nserver {\n  limit_req zone=api burst=10;\n}"
    segs = [SegmentIn(0, conf, "ocr"), SegmentIn(1, "Plain sentence about nothing at all.", "ocr")]
    assert note.code_blocks(segs) == [conf]
    md = note.compose("", [{"type": "fact", "text": "x"}], None, [], [], [conf])
    assert "## Source text, exact\n```\nlimit_req_zone" in md and md.count("```") == 2


def test_number_words_become_digits_but_titles_and_bare_numbers_stay():
    assert note.numerals("order by id limit fifty") == "order by id limit 50"
    assert note.numerals("Five hundred ml of water, then forty-five minutes") == \
        "500 ml of water, then 45 minutes"
    assert note.numerals("Ten minutes of mobility") == "10 minutes of mobility"
    assert note.numerals("wake at five, one of them") == "wake at five, one of them"
    assert note.numerals("read Four Thousand Weeks") == "read Four Thousand Weeks"


def test_dictated_flags_keep_their_hyphens():
    out = note.despeak("run dash dash env file dot env dash dash no cache dir dash d")
    assert "--env-file .env" in out and "--no-cache-dir" in out


def test_a_correction_worded_with_original_retires_the_earlier_value():
    units = [{"type": "fact", "text": "The search cluster initially had 6 nodes"},
             {"type": "fact", "text": "The original cluster had 8 nodes, not 6"}]
    d = {}
    assert [u["text"] for u in note._supersede(units, d)] == ["The original cluster had 8 nodes, not 6"]


def test_placeholder_platform_title_is_replaced_by_a_headline_from_the_content():
    assert note.real_title("Video by ml.swe") == ""
    assert note.real_title("Reel by x") == "" and note.real_title("Video bytes explained") != ""
    units = [{"type": "fact", "text": "Idempotency keys make retries safe " * 4}]
    out, _ = note._candidates("Video by ml.swe", "body", units, None, [], [], {}, [], {}, "m")
    assert not out[0].title.startswith("Video by") and 0 < len(out[0].title) <= 81
    assert note._candidates("Real", "b", units, None, [], [], {}, [], {}, "m")[0][0].title == "Real"


SCOPE_SEGS = [SegmentIn(0, "intro chat about weather with Zed Quill and cats", "t=0-5"),
              SegmentIn(1, "the tool called pgbouncer pools connections for postgres", "t=5-9")]
SCOPE_FOCUS = {"context": "", "entities": [], "gaps": [],
               "units": [{"type": "resource", "text": "pgbouncer pools connections"}]}
SCOPE_REPLY = {"context": "", "entities": ["Zed Quill", "pgbouncer"], "gaps": [],
               "units": [{"type": "fact", "text": "They chat about weather with Zed Quill"},
                         {"type": "resource", "text": "pgbouncer pools connections"}]}


def test_build_with_intent_keeps_only_matching_units():
    cands, _ = note.build(reg(Fake([SCOPE_REPLY, SCOPE_FOCUS])), SCOPE_SEGS, intent="the connection pooling tool")
    n = cands[0]
    assert "pgbouncer pools connections" in n.body and "weather" not in n.body
    assert "Also in the source" not in n.body and n.data["scope"] == "scoped"
    assert [u["text"] for u in n.data["units"]] == ["pgbouncer pools connections"]
    assert [c.title for c in cands if c.kind == "unit"] == ["pgbouncer pools connections"]


def test_build_scoped_mentions_only_from_kept_units():
    cands, _ = note.build(reg(Fake([SCOPE_REPLY, SCOPE_FOCUS])), SCOPE_SEGS, intent="the connection pooling tool")
    body = next(c.body for c in cands if c.kind == "mentions")
    assert "pgbouncer" in body and "Zed Quill" not in body


def test_scoping_trusts_the_model_not_word_overlap_for_category_reasons():
    segs = [SegmentIn(0, "calm music helps you focus. Blinding Lights by The Weeknd, "
                         "then Levitating by Dua Lipa. also my cat is asleep", "t=0-20")]
    first = {"context": "", "entities": [], "gaps": [],
             "units": [{"type": "fact", "text": "Calm music helps you focus"},
                       {"type": "fact", "text": "my cat is asleep"}]}
    focus = {"context": "", "entities": [], "gaps": [],
             "units": [{"type": "resource", "text": "Blinding Lights by The Weeknd"},
                       {"type": "resource", "text": "Levitating by Dua Lipa"}]}
    fake = Fake([first, focus])
    cands, _ = note.build(reg(fake), segs, intent="just the music")
    body = cands[0].body
    assert len(fake.calls) == 2  # a stray "music" in one unit no longer skips the model
    assert "Blinding Lights" in body and "Levitating" in body and "cat is asleep" not in body
    assert cands[0].data["scope"] == "scoped"


def test_focus_pass_failure_keeps_the_note_unscoped():
    class Boom(Fake):
        def generate(self, messages, *, json_schema=None, max_tokens=None):
            if self.calls:
                raise ProviderError("down")
            return super().generate(messages)

    segs = [SegmentIn(0, "intro chat about weather and cats today", "t=0-5")]
    reply = {"context": "", "units": [{"type": "fact", "text": "Chat about weather and cats"}],
             "entities": [], "gaps": []}
    cands, _ = note.build(reg(Boom([reply])), segs, intent="the music")
    assert cands[0].data["scope"] == "unscoped" and "weather and cats" in cands[0].body
