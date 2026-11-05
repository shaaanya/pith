# Capabilities and task routing

A backend declares what it can do with a `Capabilities` record (`providers/ports.py`). The registry uses
it so an unsupported use is detected up front instead of failing at call time.

| Field | Meaning | Set by |
|---|---|---|
| `text` | Can generate text (chat/completion) | always for `openai_compat`, `anthropic`, `heuristic`; `cli` unless `capabilities` is overridden |
| `json_mode` | Server supports schema-constrained JSON output | declared in config (`capabilities = ["json_mode"]`); the heuristic backend reports it |
| `vision` | Can describe images | declared in config |
| `embeddings` | Can embed text | `openai_compat` when `embed_model` is set |
| `rerank` | Can rerank documents | declared |
| `transcribe` | Speech to text | `whisper_cpp`; `openai_compat` when declared |
| `ocr` | Image to text | `tesseract` |
| `context_window` | Tokens (default 8192) used to size prompts and decide on map-reduce | `context_window` in config |

## Tasks

A task name selects a chain of backends. The task names are exactly:

| Task | Needs capability | Used by |
|---|---|---|
| `distill` | `text` | distillation |
| `classify` | `text` | accepted and routed like any text task and listed by `doctor`/`egress`, but no pipeline stage calls it yet |
| `embed` | `embeddings` | embedding index, hybrid search, near-duplicate detection |
| `rerank` | `rerank` | optional search rerank |
| `transcribe` | `transcribe` | media extractor |
| `describe` | `vision` | image and video-frame description |
| `ocr` | `ocr` | image extractor |
| `answer` | `text` | `ask` |

## Resolution rules (`providers/registry.py`)

- `[tasks] <task> = ["a", "b:model"]` is an ordered fallback list. `name:model` overrides the `model` key
  of backend `name` for that route.
- A task with no `[tasks]` entry uses every configured backend in config order.
- A backend that lacks the capability the task needs is dropped from that task's chain.
- For text tasks the `heuristic` backend is always appended last (and moved there if configured earlier),
  and one is created automatically if none is configured.
- Remote backends (`locality = "remote"`) are filtered out of every chain unless `[privacy] allow_remote =
  true`; each skip is recorded and shown by `doctor`. Asking for a remote backend explicitly while blocked
  raises `RemoteBlocked`.
- Unknown backend names in `[tasks]` or unknown `type` values fail when the config is loaded.
- `ask` uses the `answer` chain minus `heuristic`.

## Detection

`infoparser doctor` reports each backend's declared capabilities and, for local `openai_compat` servers,
probes reachability and the embeddings endpoint with canned strings (3 s timeout). It does not probe JSON
mode, does not contact remote backends, and never executes `cli` backends (it only checks the command is on
PATH). Capabilities are declared in config; a declaration that the server does not honour is found at call
time and handled by the repair/fallback path.
