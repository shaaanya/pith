# Backends: capabilities and task routing

A backend declares what it can do with a `Capabilities` record (`providers/ports.py`). The registry uses
it so an unsupported use is detected up front instead of failing at call time.

| Field | Meaning | Set by |
|---|---|---|
| `text` | Can generate text (chat/completion) | always for `openai_compat`, `anthropic`, `heuristic`, `cli` |
| `json_mode` | Server supports schema-constrained JSON output | declared in config (`capabilities = ["json_mode"]`); the heuristic backend reports it |
| `vision` | Can describe images | declared in config on `openai_compat` (chat message with base64 `image_url` parts; UNVERIFIED against a real vision model). No other backend implements it |
| `embeddings` | Can embed text | `openai_compat` when `embed_model` is set |
| `rerank` | Can rerank documents | declared in config on `openai_compat` (Jina/Cohere-style `POST /rerank`; UNVERIFIED against a real server). No other backend implements it |
| `transcribe` | Speech to text | `whisper_cpp`; `openai_compat` when declared |
| `ocr` | Image to text | `tesseract` only; declaring `ocr` on `openai_compat` or `cli` is a config error (use `vision` to describe images) |
| `context_window` | Tokens (default 8192) used to size prompts and decide on map-reduce. Match the server's real context: Ollama's `/v1` endpoint truncated a default-sized batch to 4096 prompt tokens without an error, so an Ollama backend should set `context_window = 4096` (or raise the server's context) | `context_window` in config |

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
- A backend is in a task's chain only if it declares the capability the task needs AND really has the
  method that serves it (`generate`, `embed`, `rerank`, `transcribe`, `read` for `ocr`, `describe`).
- A declared capability that the backend type cannot serve fails when the config is loaded (for example
  `ocr` or `embeddings` without `embed_model` on `openai_compat`, anything but `text`/`json_mode` on `cli`).
- For text tasks the `heuristic` backend is always appended last (and moved there if configured earlier),
  and one is created automatically if none is configured.
- Remote backends (`locality = "remote"`) are filtered out of every chain unless `[privacy] allow_remote =
  true`; each skip is recorded and shown by `doctor`. Asking for a remote backend explicitly while blocked
  raises `RemoteBlocked`.
- Unknown backend names in `[tasks]` or unknown `type` values fail when the config is loaded.
- `ask` uses the `answer` chain minus `heuristic`.

## Detection

`pith doctor` reports each backend's declared capabilities and, for local `openai_compat` servers,
probes reachability and the embeddings endpoint with canned strings (3 s timeout). It does not probe JSON
mode, does not contact remote backends, and never executes `cli` backends (it only checks the command is on
PATH). Capabilities are declared in config and only embeddings are probed; a declaration that the server
does not honour (a model without vision, a server without `/rerank`) is found at call time: a failed
`rerank` is skipped with a warning, a failed `describe` fails the item.
