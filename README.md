# InfoParser

Local-first knowledge capture. Save a link, file, video or note; get one searchable note that holds
the actual information (steps, numbers, names), not a description of it. Runs on your machine; models
are optional.

```
uv sync
uv run infoparser                                    # worker + dashboard on 127.0.0.1
uv run infoparser submit "<url or text>" --why "what I want from it"
uv run infoparser search "keywords"
uv run infoparser ask "question about what I saved"
```

Models, transcription and OCR are set in the dashboard's Settings tab or `config.toml`
(see `config.sample.toml`). With no model, a deterministic fallback still stores and searches.

## How it works

```mermaid
flowchart LR
  subgraph IN[Capture]
    S((Save)) --> A[CLI / folder / HTTP / Telegram export]
    A --> Q[(Inbox queue)]
  end
  subgraph WK[Worker]
    Q --> D{Type?}
    D -->|web, PDF, office| E1[Extract text]
    D -->|image| E2[OCR]
    D -->|video, audio| G{Captions?}
    G -->|yes| E3[Use captions]
    G -->|no| T{Transcriber?}
    T -->|yes| E4[Transcribe]
    T -->|no| C[/Needs clarification/]
    E1 & E2 & E3 & E4 --> K[Chunk]
    K --> N[Build note]
  end
  subgraph ST[Store]
    N --> DB[(SQLite + FTS5)]
    N --> B[(Original blobs)]
    DB --> V[Markdown vault]
  end
  subgraph US[Use]
    DB --> R[Search / Ask with citations]
    R --> O((Answer))
  end
```

## Building a note

A small local model only finds the facts. Code checks and writes the note.

```mermaid
flowchart LR
  subgraph PREP[Code]
    P1[Fix mishearings from the description] --> P2[Dictated symbols and number words to code and digits]
  end
  subgraph MODEL[Model]
    M1[Extract typed units: step, fact, claim, resource, warning]
  end
  subgraph CHECK[Code]
    V1{Number or words not in source?}
    V1 -->|yes| X((Drop unit))
    V1 -->|no| V2{Commentary or promo?}
    V2 -->|yes| X
    V2 -->|no| V3[Keep, link to source segment]
    V3 --> V4{Your reason matched?}
    V4 -->|no| M2[Focused second pass]
    V4 -->|yes| W[Compose note + mention index]
    M2 --> W
  end
  P2 --> M1 --> V1
  W --> DONE((Note))
```

- Your reason for saving is used only if you wrote it. It is never guessed.
- A fact the source does not support is dropped. Incomplete beats wrong.
- On 14 synthetic cases with `gemma4:e4b`: recall 0.99, no blocking failures
  ([results](docs/note-pipeline.md)).

## Docs

[architecture](docs/architecture.md) · [pipeline](docs/pipeline.md) · [note pipeline](docs/note-pipeline.md) ·
[configuration](docs/configuration.md) · [limitations](docs/limitations.md)

Python 3.13. Some paths are unverified; read the limitations first.
