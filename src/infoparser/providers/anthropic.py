"""Anthropic Messages API backend (thin, urllib only). locality="remote": blocked unless
[privacy] allow_remote=true. LIVE CALLS UNVERIFIED (no credentials here): the wire format is tested
only against a local fixture server (tests/stubs/anthropic_stub.py).

POST {base_url}/v1/messages with headers x-api-key, anthropic-version, content-type. System messages
are lifted into the top-level `system` field. JSON-schema requests embed the schema in the system
prompt and ask for JSON only (native structured output varies by model, so it is not used).
Only content blocks with type == "text" are returned. The API key is read from the env var NAMED in
config and is never logged or included in error strings.

Spec keys: type = "anthropic"; model (required, from config only); api_key_env (required, env var
NAME); base_url (default https://api.anthropic.com); anthropic_version (default 2023-06-01);
max_tokens (default 4096; generate(max_tokens=) overrides); timeout (seconds, 120);
context_window (optional int).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .locality import opener
from .ports import Capabilities, CapabilityError, GenResult, ProviderError, schema_instruction


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class AnthropicBackend:  # pylint: disable=too-many-instance-attributes  # one attribute per spec key
    """Remote text backend for the Anthropic Messages API."""

    locality = "remote"

    # config record: each argument is one spec key
    def __init__(self, name, model, api_key_env,  # pylint: disable=too-many-arguments,too-many-positional-arguments  # one arg per config key
                 base_url="https://api.anthropic.com", anthropic_version="2023-06-01",
                 max_tokens=4096, timeout=120, context_window=200_000):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme != "https" and not (u.scheme == "http" and u.hostname in _LOOPBACK):
            raise ValueError("base_url must be https (http only for loopback)")
        self.name, self.model, self.api_key_env = name, model, api_key_env
        self.base_url, self.anthropic_version = base_url.rstrip("/"), anthropic_version
        self.max_tokens, self.timeout = max_tokens, timeout
        self.capabilities = Capabilities(text=True, context_window=context_window)

    @classmethod
    def from_spec(cls, name, spec):
        """Build from a `[backends.<name>]` spec (model and api_key_env required)."""
        return cls(name, spec["model"], spec["api_key_env"],
                   spec.get("base_url", "https://api.anthropic.com"),
                   spec.get("anthropic_version", "2023-06-01"), spec.get("max_tokens", 4096),
                   spec.get("timeout", 120), spec.get("context_window", 200_000))

    def generate(self, messages, *, json_schema=None, max_tokens=None) -> GenResult:
        """Call the Messages API; ProviderError on any failure (the key is never in the message)."""
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"{self.name}: env var {self.api_key_env} is not set")
        system = [m["content"] for m in messages if m["role"] == "system"]
        if json_schema is not None:
            system.append(schema_instruction(json_schema))
        body = {"model": self.model, "max_tokens": max_tokens or self.max_tokens,
                "messages": [{"role": m["role"], "content": m["content"]}
                             for m in messages if m["role"] != "system"]}
        if system:
            body["system"] = "\n\n".join(system)
        req = urllib.request.Request(
            self.base_url + "/v1/messages", data=json.dumps(body).encode(), method="POST",
            headers={"x-api-key": key, "anthropic-version": self.anthropic_version,
                     "content-type": "application/json"})
        try:
            # http is only accepted for loopback (see __init__): never via a proxy
            with opener(self.base_url.startswith("http:")).open(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise ProviderError(
                    f"{self.name}: refusing to follow HTTP {e.code} redirect") from None
            raise ProviderError(f"{self.name}: HTTP {e.code} {self._api_message(e)}") from None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from None
        try:
            text = "".join(b["text"] for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e
        return GenResult(text, data.get("model", self.model), self.name)

    @staticmethod
    def _api_message(e: urllib.error.HTTPError) -> str:
        """Error type/message from the API body, else the HTTP reason."""
        try:
            err = json.loads(e.read())["error"]
            return f"{err.get('type', '')}: {err.get('message', '')}".strip(": ")
        except (ValueError, KeyError, TypeError, OSError):
            return str(e.reason)

    def embed(self, texts):
        """Not supported: raises CapabilityError."""
        raise CapabilityError(f"{self.name}: embeddings not supported")
