"""How an inbox row is shown to people (never the dedupe key)."""


def inbox_label(row, limit: int = 80) -> str:
    """URL items show the URL exactly as submitted; files their name; text a one-line excerpt."""
    payload = (row["payload_text"] or "").strip()
    if row["kind_hint"] == "url" and payload:
        return payload
    return row["original_filename"] or payload[:limit].replace("\n", " ")
