"""OpenAI-wire backend (Ollama, llama.cpp server, LM Studio, vLLM, hosted OpenAI-style) via urllib.

Spec keys: type = "openai_compat"; base_url (required, e.g. http://localhost:11434/v1);
model (required); api_key_env (env var NAME holding the key, optional); locality
("local"|"remote", default "local"); embed_model (enables embeddings); timeout
(seconds, default 120); capabilities (list of extra Capabilities field names, e.g.
["json_mode", "transcribe", "vision"]; "text" is always on); transcribe_model
(default: model); context_window.
json_mode declared -> response_format json_schema; otherwise the schema is put in the prompt.
/audio/transcriptions is UNVERIFIED against a real server (only the in-process stub).
"""
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .ports import (Capabilities, CapabilityError, EmbedResult, GenResult, ProviderError,
                    TimedText, schema_instruction)


class OpenAICompatBackend:
    def __init__(self, name, base_url, model, api_key_env=None, locality="local",
                 embed_model=None, timeout=120, capabilities: Capabilities | None = None,
                 transcribe_model=None):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.locality, self.embed_model = api_key_env, locality, embed_model
        self.timeout, self.transcribe_model = timeout, transcribe_model or model
        base = capabilities or Capabilities()
        self.capabilities = Capabilities(**{**base.__dict__, "text": True,
                                            "embeddings": base.embeddings or bool(embed_model)})

    @classmethod
    def from_spec(cls, name, spec):
        caps = {c: True for c in spec.get("capabilities", [])}
        if "context_window" in spec:
            caps["context_window"] = spec["context_window"]
        return cls(name, spec["base_url"], spec["model"], spec.get("api_key_env"),
                   spec.get("locality", "local"), spec.get("embed_model"),
                   spec.get("timeout", 120), Capabilities(**caps), spec.get("transcribe_model"))

    def _headers(self):
        h = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise ProviderError(f"{self.name}: env var {self.api_key_env} is not set")
            h["Authorization"] = f"Bearer {key}"
        return h

    def _call(self, path, body: bytes, content_type="application/json"):
        req = urllib.request.Request(self.base_url + path, data=body, method="POST",
                                     headers={"Content-Type": content_type, **self._headers()})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ProviderError(f"{self.name}: HTTP {e.code} {e.read()[:200]!r}") from e
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
            raise ProviderError(f"{self.name}: {e}") from e

    def generate(self, messages, *, json_schema=None, max_tokens=None) -> GenResult:
        body = {"model": self.model, "messages": list(messages)}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if json_schema is not None:
            if self.capabilities.json_mode:
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "output", "schema": json_schema, "strict": True}}
            else:
                body["messages"] = [*messages, {"role": "user", "content": schema_instruction(json_schema)}]
        data = self._call("/chat/completions", json.dumps(body).encode())
        try:
            return GenResult(data["choices"][0]["message"]["content"], data.get("model", self.model), self.name)
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e

    def embed(self, texts) -> EmbedResult:
        if not self.embed_model:
            raise CapabilityError(f"{self.name}: no embed_model configured")
        data = self._call("/embeddings", json.dumps({"model": self.embed_model, "input": texts}).encode())
        try:
            vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except (KeyError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e
        return EmbedResult(f"{self.name}:{self.embed_model}", vecs)

    def transcribe(self, path: Path, language=None) -> list[TimedText]:
        if not self.capabilities.transcribe:
            raise CapabilityError(f"{self.name}: transcribe not declared")
        b = uuid.uuid4().hex
        fields = {"model": self.transcribe_model, "response_format": "verbose_json"}
        if language:
            fields["language"] = language
        parts = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                         for k, v in fields.items())
        parts += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{Path(path).name}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n").encode()
        parts += Path(path).read_bytes() + f"\r\n--{b}--\r\n".encode()
        data = self._call("/audio/transcriptions", parts, f"multipart/form-data; boundary={b}")
        segs = data.get("segments") or [{"start": 0.0, "end": 0.0, "text": data.get("text", "")}]
        return [TimedText(float(s["start"]), float(s["end"]), s["text"].strip()) for s in segs]
