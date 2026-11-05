"""OpenAI-wire backend (Ollama, llama.cpp server, LM Studio, vLLM, hosted OpenAI-style) via urllib.

Spec keys: type = "openai_compat"; base_url (required, e.g. http://localhost:11434/v1);
model (required); api_key_env (env var NAME holding the key, optional); locality
("local"|"remote"; default: local for a loopback host, remote for any other host);
embed_model (enables embeddings); timeout (seconds, default 120); capabilities (list of extra
Capabilities field names: json_mode, transcribe, vision, rerank, embeddings; "text" is always on;
"ocr" is rejected, there is no OpenAI-wire OCR call); transcribe_model, vision_model,
rerank_model (each defaults to model); context_window.
json_mode declared -> response_format json_schema; otherwise the schema is put in the prompt.
vision -> describe() sends the images as base64 `image_url` parts of a chat message;
rerank -> rerank() POSTs {model, query, documents} to /rerank (Jina/Cohere-style, served by
llama.cpp and vLLM) and reads results[].relevance_score.
/audio/transcriptions, vision describe and /rerank are UNVERIFIED against a real server (only the
in-process stubs).
"""
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .locality import resolve
from .ports import (
    Capabilities,
    CapabilityError,
    EmbedResult,
    GenResult,
    ProviderError,
    TimedText,
    schema_instruction,
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the Authorization header must not leave base_url."""

    def redirect_request(self, *_a, **_k):  # pylint: disable=signature-differs
        """Refuse: the 30x then surfaces as an HTTPError."""
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class OpenAICompatBackend:  # pylint: disable=too-many-instance-attributes  # plain spec values
    """Chat, embeddings and transcription over an OpenAI-style HTTP API."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments  # mirrors spec keys
    def __init__(self, name, base_url, model, api_key_env=None, locality="local",
                 embed_model=None, timeout=120, capabilities: Capabilities | None = None,
                 transcribe_model=None):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.locality, self.embed_model = api_key_env, locality, embed_model
        self.timeout, self.transcribe_model = timeout, transcribe_model or model
        self.vision_model = self.rerank_model = model
        base = capabilities or Capabilities()
        self.capabilities = Capabilities(**{**base.__dict__, "text": True,
                                            "embeddings": base.embeddings or bool(embed_model)})

    @classmethod
    def from_spec(cls, name, spec):
        """Build from a config spec (see module docstring)."""
        caps = {c: True for c in spec.get("capabilities", [])}
        if "context_window" in spec:
            caps["context_window"] = spec["context_window"]
        if caps.get("ocr"):
            raise ValueError("capability 'ocr' is not implemented by openai_compat "
                             "(use a tesseract backend, or declare 'vision' to describe images)")
        if caps.get("embeddings") and not spec.get("embed_model"):
            raise ValueError("capability 'embeddings' needs embed_model")
        b = cls(name, spec["base_url"], spec["model"], spec.get("api_key_env"),
                resolve(spec, spec["base_url"]), spec.get("embed_model"),
                spec.get("timeout", 120), Capabilities(**caps), spec.get("transcribe_model"))
        b.vision_model = spec.get("vision_model") or b.model
        b.rerank_model = spec.get("rerank_model") or b.model
        return b

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
            with _OPENER.open(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ProviderError(f"{self.name}: HTTP {e.code} {e.read()[:200]!r}") from e
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
            raise ProviderError(f"{self.name}: {e}") from e

    def generate(self, messages, *, json_schema=None, max_tokens=None) -> GenResult:
        """Chat completion; a JSON schema goes in response_format or into the prompt."""
        body = {"model": self.model, "messages": list(messages)}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if json_schema is not None:
            if self.capabilities.json_mode:
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "output", "schema": json_schema, "strict": True}}
            else:
                body["messages"] = [
                    *messages, {"role": "user", "content": schema_instruction(json_schema)}]
        data = self._call("/chat/completions", json.dumps(body).encode())
        try:
            return GenResult(data["choices"][0]["message"]["content"],
                             data.get("model", self.model), self.name)
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e

    def embed(self, texts) -> EmbedResult:
        """Embed texts with embed_model."""
        if not self.embed_model:
            raise CapabilityError(f"{self.name}: no embed_model configured")
        data = self._call("/embeddings",
                          json.dumps({"model": self.embed_model, "input": texts}).encode())
        try:
            vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
        except (KeyError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e
        return EmbedResult(f"{self.name}:{self.embed_model}", vecs)

    def transcribe(self, path: Path, language=None) -> list[TimedText]:
        """Timed transcript through /audio/transcriptions (UNVERIFIED against a real server)."""
        if not self.capabilities.transcribe:
            raise CapabilityError(f"{self.name}: transcribe not declared")
        b = uuid.uuid4().hex
        fields = {"model": self.transcribe_model, "response_format": "verbose_json"}
        if language:
            fields["language"] = language
        parts = b"".join(
            f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items())
        parts += (f'--{b}\r\nContent-Disposition: form-data; name="file"; '
                  f'filename="{Path(path).name}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n").encode()
        parts += Path(path).read_bytes() + f"\r\n--{b}--\r\n".encode()
        data = self._call("/audio/transcriptions", parts, f"multipart/form-data; boundary={b}")
        segs = data.get("segments") or [{"start": 0.0, "end": 0.0, "text": data.get("text", "")}]
        return [TimedText(float(s["start"]), float(s["end"]), s["text"].strip()) for s in segs]

    def describe(self, images: list[Path], prompt: str) -> str:
        """Describe images through a chat message with `image_url` parts (UNVERIFIED live)."""
        if not self.capabilities.vision:
            raise CapabilityError(f"{self.name}: vision not declared")
        parts = [{"type": "text", "text": prompt}]
        for img in images:
            mime = mimetypes.guess_type(str(img))[0] or "image/png"
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        body = {"model": self.vision_model, "messages": [{"role": "user", "content": parts}]}
        data = self._call("/chat/completions", json.dumps(body).encode())
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        """Relevance scores in `docs` order from a Jina-style /rerank endpoint (UNVERIFIED live)."""
        if not self.capabilities.rerank:
            raise CapabilityError(f"{self.name}: rerank not declared")
        body = {"model": self.rerank_model, "query": query, "documents": docs}
        data = self._call("/rerank", json.dumps(body).encode())
        try:
            scores = [0.0] * len(docs)
            for res in data["results"]:
                scores[int(res["index"])] = float(res["relevance_score"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"{self.name}: malformed response") from e
        return scores
