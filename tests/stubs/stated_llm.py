"""Deterministic distiller reply with one verbatim `stated` quote and one fabricated one.

Used by the model-independence matrix so the stated-evidence contract is exercised by model
output. Ask prompts are delegated to fake_llm. Runnable as a CLI: prompt on stdin.
"""
import json
import sys


try:
    from . import fake_llm
except ImportError:  # run as a script (cli backend): sibling module on sys.path
    import fake_llm

FABRICATED = "Zebras negotiated the first quantum database treaty in 1832."
_START = "Reply with ONLY JSON matching the given schema."
_END = "Respond with ONLY a JSON object"


def source_text(prompt: str) -> str:
    """The text being distilled: what sits between the system instruction and the schema."""
    body = prompt.split(_START, 1)[-1].split(_END, 1)[0]
    return body.replace("user:", "", 1).strip()


def verbatim_quote(text: str, limit: int = 70) -> str:
    """A prefix of `text`, cut at a word boundary, that is a verbatim substring."""
    head = " ".join(text.split())[:limit]
    return head.rsplit(" ", 1)[0] if " " in head else head


def reply_for(prompt: str) -> str:
    """JSON reply for a distill prompt; plain delegation for ask prompts."""
    if '<excerpt n="1">' in prompt:
        return fake_llm.reply_for(prompt)
    quote = verbatim_quote(source_text(prompt))
    if '"entries"' in prompt:  # collection profile
        return json.dumps({"title": "Reading list", "summary": quote,
                           "entries": [{"name": quote, "quote": quote}]})
    return json.dumps({"summary": f"summary: {quote}",
                       "insights": [{"text": quote, "quote": quote},
                                    {"text": FABRICATED, "quote": FABRICATED}]})


if __name__ == "__main__":
    print(reply_for(sys.stdin.read()))
