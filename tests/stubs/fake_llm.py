"""Fake LLM CLI: reads the prompt on stdin (or argv[1]), prints deterministic JSON."""
import hashlib
import json
import sys


def reply_for(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    return json.dumps({"summary": f"stub summary {digest}",
                       "insights": [{"text": prompt.strip()[:60], "quote": prompt.strip()[:60]}]})


if __name__ == "__main__":
    print(reply_for(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()))
