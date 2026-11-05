"""How an inbox row is shown to people (never the dedupe key)."""


def inbox_label(row, limit: int = 80) -> str:
    """URL items show the URL exactly as submitted; files their name; text a one-line excerpt."""
    payload = (row["payload_text"] or "").strip()
    if row["kind_hint"] == "url" and payload:
        return payload
    return row["original_filename"] or payload[:limit].replace("\n", " ")


def submitted_url(row) -> str | None:
    """The URL as the user submitted it (fetch and cite this); None for non-URL items.

    canonical_url is only the dedupe key. Rows without a payload fall back to it.
    """
    canonical = row["canonical_url"]
    if not canonical:
        return None
    payload = (row["payload_text"] if "payload_text" in row.keys() else None) or ""
    return payload.strip() or canonical
