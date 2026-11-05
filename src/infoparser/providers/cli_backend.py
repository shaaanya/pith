"""Subprocess backend: runs a command, returns stdout.

Spec keys: type = "cli"; command (list[str], required); prompt_via ("stdin"|"arg",
default "stdin"; "arg" appends the prompt as the last argv item); locality
("local"|"remote", default "local"); timeout (seconds, default 300);
capabilities (list of Capabilities field names, default ["text"]); context_window.
The JSON schema is embedded in the prompt text.
"""
import subprocess

from .ports import Capabilities, CapabilityError, GenResult, ProviderError, flatten_messages, schema_instruction


class CliBackend:
    def __init__(self, name, command, prompt_via="stdin", locality="local", timeout=300,
                 capabilities: Capabilities | None = None):
        if prompt_via not in ("stdin", "arg"):
            raise ValueError(f"prompt_via must be stdin|arg, got {prompt_via!r}")
        self.name, self.command, self.prompt_via = name, list(command), prompt_via
        self.locality, self.timeout = locality, timeout
        self.capabilities = capabilities or Capabilities(text=True)

    @classmethod
    def from_spec(cls, name, spec):
        caps = {c: True for c in spec.get("capabilities", ["text"])}
        if "context_window" in spec:
            caps["context_window"] = spec["context_window"]
        return cls(name, spec["command"], spec.get("prompt_via", "stdin"),
                   spec.get("locality", "local"), spec.get("timeout", 300), Capabilities(**caps))

    def generate(self, messages, *, json_schema=None, max_tokens=None) -> GenResult:
        prompt = flatten_messages(messages)
        if json_schema is not None:
            prompt += "\n\n" + schema_instruction(json_schema)
        argv = self.command + ([prompt] if self.prompt_via == "arg" else [])
        try:
            p = subprocess.run(argv, input=prompt if self.prompt_via == "stdin" else None,
                               capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProviderError(f"{self.name}: {e}") from e
        if p.returncode != 0:
            raise ProviderError(f"{self.name}: exit {p.returncode}: {p.stderr.strip()[:300]}")
        return GenResult(p.stdout.strip(), " ".join(self.command[:1]), self.name)

    def embed(self, texts):
        raise CapabilityError(f"{self.name}: embeddings not supported")
