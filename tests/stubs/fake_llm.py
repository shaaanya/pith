"""Fake LLM CLI: reads the prompt on stdin (or argv[1]), prints deterministic JSON."""
import hashlib
import json
import sys


def reply_for(prompt: str) -> str:
    """Canned answer (with a citation) for `ask`, else deterministic distill JSON."""
    if '<excerpt n="1">' in prompt:  # `ask` prompt: answer with a citation
        return "The saved excerpts address this question [1]."
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    return json.dumps({"summary": f"stub summary {digest}",
                       "insights": [{"text": prompt.strip()[:60], "quote": prompt.strip()[:60]}]})


if __name__ == "__main__":
    print(reply_for(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()))
