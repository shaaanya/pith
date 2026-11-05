import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def new_id() -> str:
    """26-char ULID: 48-bit ms timestamp + 80 random bits, lexicographically time-sortable."""
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10))
    return "".join(_ALPHABET[(n >> s) & 31] for s in range(125, -1, -5))


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
