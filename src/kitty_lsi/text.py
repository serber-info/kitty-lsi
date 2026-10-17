"""Safe, terminal-cell-aware handling of untrusted filenames."""

import unicodedata
from wcwidth import wcswidth


def safe_text(value: str) -> str:
    """Filenames are untrusted terminal input, never escape sequences."""
    return "".join(
        char if unicodedata.category(char)[0] != "C"
        and char not in "\u2028\u2029\U0010eeee" else "?"
        for char in value
    )


def truncate(value: str, columns: int) -> str:
    if wcswidth(value) <= columns:
        return value
    result = ""
    for char in value:
        if wcswidth(result + char) > columns - 1:
            break
        result += char
    return result + "…" if columns > 0 else ""


