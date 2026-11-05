"""Subprocess backend: runs a command, returns its (terminal-cleaned) stdout.

Spec keys: type = "cli"; command (list[str], required); prompt_via ("stdin"|"arg",
default "stdin"; "arg" appends the prompt as the last argv item); locality
("local"|"remote", default "local"); timeout (seconds, default 300);
capabilities (list of Capabilities field names, default ["text"]); context_window.
The JSON schema is embedded in the prompt text.

Some CLIs write terminal control sequences even when stdout is a pipe (word-wrap
rewrites such as "erase line" / "cursor left", spinner frames). clean_terminal_output()
replays those onto a line buffer so only the text a terminal would show remains.
"""
import re
import subprocess

from .ports import (Capabilities, CapabilityError, GenResult, ProviderError, flatten_messages,
                    schema_instruction)

_ESC = re.compile(r"\x1b(?:\[([0-9;?]*)([ -/]*[@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")


def clean_terminal_output(text: str) -> str:
    """Render `text` as a terminal would: apply cursor-left/right, erase-line, CR and
    backspace; drop every other escape sequence (colour, cursor visibility, OSC titles)."""
    lines, cur, col = [], [], 0
    pos = 0
    while pos < len(text):
        esc = _ESC.match(text, pos) if text[pos] == "\x1b" else None
        if esc:
            pos = esc.end()
            params, final = esc.group(1), esc.group(2)
            num = int(params.split(";")[0] or 1) if params and params[0].isdigit() else 1
            if final == "D":
                col = max(0, col - num)
            elif final == "C":
                col += num
            elif final == "G":
                col = max(0, num - 1)
            elif final == "K" and params in (None, "", "0"):
                del cur[col:]
            elif final == "K" and params == "2":
                cur.clear()
            continue
        ch = text[pos]
        pos += 1
        if ch == "\n":
            lines.append("".join(cur))
            cur, col = [], 0
        elif ch == "\r":
            col = 0
        elif ch == "\b":
            col = max(0, col - 1)
        elif ch == "\x1b":
            continue  # lone ESC that starts no known sequence
        else:
            cur[col:col + 1] = [ch]  # overwrite at the cursor, or append at the end
            col += 1
    lines.append("".join(cur))
    return "\n".join(lines)


class CliBackend:
    """Text generation through any command that reads a prompt and prints an answer."""

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments  # mirrors the spec keys
    def __init__(self, name, command, prompt_via="stdin", locality="local", timeout=300,
                 capabilities: Capabilities | None = None):
        if prompt_via not in ("stdin", "arg"):
            raise ValueError(f"prompt_via must be stdin|arg, got {prompt_via!r}")
        self.name, self.command, self.prompt_via = name, list(command), prompt_via
        self.locality, self.timeout = locality, timeout
        self.capabilities = capabilities or Capabilities(text=True)

    @classmethod
    def from_spec(cls, name, spec):
        """Build from a config spec (see module docstring)."""
        caps = {c: True for c in spec.get("capabilities", ["text"])}
        if "context_window" in spec:
            caps["context_window"] = spec["context_window"]
        return cls(name, spec["command"], spec.get("prompt_via", "stdin"),
                   spec.get("locality", "local"), spec.get("timeout", 300), Capabilities(**caps))

    def generate(self, messages, *, json_schema=None, max_tokens=None) -> GenResult:
        """Run the command with the flattened prompt; `max_tokens` is not expressible here."""
        del max_tokens
        prompt = flatten_messages(messages)
        if json_schema is not None:
            prompt += "\n\n" + schema_instruction(json_schema)
        argv = self.command + ([prompt] if self.prompt_via == "arg" else [])
        try:
            p = subprocess.run(argv, input=prompt if self.prompt_via == "stdin" else None,
                               capture_output=True, text=True, errors="replace",
                               timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProviderError(f"{self.name}: {e}") from e
        if p.returncode != 0:
            raise ProviderError(f"{self.name}: exit {p.returncode}: {p.stderr.strip()[:300]}")
        return GenResult(clean_terminal_output(p.stdout).strip(), " ".join(self.command[:1]),
                         self.name)

    def embed(self, texts):
        """Not supported by a plain command."""
        raise CapabilityError(f"{self.name}: embeddings not supported")
