"""Small, write-only implementation of Kitty's PNG/placeholder protocol.

Source: https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders
No terminal queries, cursor repositioning, temporary files or remote control.
"""

import base64
from collections.abc import Iterator

ESC = "\x1b"
PLACEHOLDER = "\U0010eeee"
# First 16 entries of the protocol's rowcolumn-diacritics table (Unicode data).
# https://sw.kovidgoyal.net/kitty/_downloads/rowcolumn-diacritics.txt
DIACRITICS = "\u0305\u030d\u030e\u0310\u0312\u033d\u033e\u033f\u0346\u034a\u034b\u034c\u0350\u0351\u0352\u0357"


def transmission(png: bytes, image_id: int, columns: int, rows: int) -> Iterator[str]:
    """Transmit a PNG and create a quiet virtual placement, chunked at 4096."""
    encoded = base64.b64encode(png).decode("ascii")
    for offset in range(0, len(encoded), 4096):
        chunk = encoded[offset:offset + 4096]
        more = int(offset + 4096 < len(encoded))
        control = f"m={more},q=2"
        if offset == 0:
            control += f",a=T,f=100,t=d,U=1,i={image_id},c={columns},r={rows}"
        yield f"{ESC}_G{control};{chunk}{ESC}\\"


def placeholder_row(image_id: int, row: int, columns: int) -> str:
    """Encode a 24-bit random image ID in foreground RGB.

The column is explicit on the first cell and inferred on subsequent cells,
as specified by Kitty. This allows arbitrary thumbnail widths.
"""
    rgb = f"{image_id >> 16};{(image_id >> 8) & 255};{image_id & 255}"
    cells = PLACEHOLDER + DIACRITICS[row] + DIACRITICS[0]
    cells += PLACEHOLDER * (columns - 1)
    return f"{ESC}[38;2;{rgb}m{cells}{ESC}[39m"
