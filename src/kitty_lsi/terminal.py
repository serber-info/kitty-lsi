"""Terminal capability and size detection without terminal input queries."""

import os
import sys


def graphics_available() -> bool:
    return bool(
        sys.stdout.isatty()
        and (os.environ.get("KITTY_WINDOW_ID") or os.environ.get("TERM") == "xterm-kitty")
        and not (os.environ.get("TMUX") or os.environ.get("STY"))
    )


