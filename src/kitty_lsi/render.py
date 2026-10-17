"""Render a section in a grid or long rows, hiding graphics/layout mechanics."""

from dataclasses import dataclass
import os
import secrets
import stat
import sys

from PIL import Image, UnidentifiedImageError
from wcwidth import wcswidth

from .graphics import placeholder_row, transmission
from .listing import long_fields
from .preview import IMAGE_EXTENSIONS, thumbnail
from .terminal import graphics_available
from .text import safe_text, truncate


@dataclass
class Card:
    name: str
    fields: list[str]
    mode: int
    entry: object
    image_id: int = 0
    dimensions: str = ""
    failed: bool = False


class Renderer:
    def __init__(self, options, error):
        self.options = options
        self.error = error
        self.graphics = not options.no_images and graphics_available()
        self.used_ids: set[int] = set()
        if not options.no_images and sys.stdout.isatty() and not self.graphics:
            print("lsi: previews require Kitty without tmux/screen; showing names only.", file=sys.stderr)

    def _card(self, entry):
        path = entry.path
        info = path.lstat()
        mode = info.st_mode
        name = safe_text(entry.name)
        opt = self.options
        if stat.S_ISDIR(mode) and opt.indicator != "none":
            name += "/"
        elif opt.indicator == "classify":
            if stat.S_ISLNK(mode):
                name += "@"
            elif stat.S_ISFIFO(mode):
                name += "|"
            elif stat.S_ISSOCK(mode):
                name += "="
            elif stat.S_ISREG(mode) and mode & 0o111:
                name += "*"
        if opt.long and stat.S_ISLNK(mode):
            name += " -> " + safe_text(os.readlink(path))
        fields = long_fields(
            path, opt.human_readable, numeric=opt.numeric_uid_gid, si=opt.si,
            hide_owner=opt.g, hide_group=opt.o, full_time=opt.full_time,
        ) if opt.long else []
        if opt.inode:
            fields.insert(0, str(info.st_ino))
        return Card(name, [safe_text(f) for f in fields], mode, entry)

    def _image(self, card, width, height):
        if not stat.S_ISREG(card.mode) or card.entry.path.suffix.lower() not in IMAGE_EXTENSIONS:
            return
        try:
            png, size = thumbnail(card.entry.path, width, height)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombWarning,
                Image.DecompressionBombError) as exc:
            self.error(OSError(f"{card.name}: {exc}"))
            card.failed = True
            return
        image_id = secrets.randbelow(0xFFFFFF) + 1
        while image_id in self.used_ids:
            image_id = secrets.randbelow(0xFFFFFF) + 1
        self.used_ids.add(image_id)
        card.image_id = image_id
        card.dimensions = f"{size[0]} × {size[1]}"
        for chunk in transmission(png, image_id, width, height):
            sys.stdout.write(chunk)

    def _image_row(self, card, row, width, height):
        if card.image_id:
            return placeholder_row(card.image_id, row, width)
        label = "[unreadable]" if card.failed else (
            "[directory]" if stat.S_ISDIR(card.mode) else
            "[link]" if stat.S_ISLNK(card.mode) else "[file]"
        )
        text = truncate(label, width) if row == height // 2 else ""
        return text + " " * (width - wcswidth(text))

    def show(self, entries):
        cards = []
        for entry in entries:
            try:
                cards.append(self._card(entry))
            except OSError as exc:
                self.error(exc)
        if not cards:
            return
        widths = [max(wcswidth(card.fields[i]) for card in cards)
                  for i in range(len(cards[0].fields))]
        for card in cards:
            card.fields = [field + " " * (widths[i] - wcswidth(field))
                           for i, field in enumerate(card.fields)]
        if not self.graphics:
            for card in cards:
                print(" ".join(card.fields) + " " + card.name if card.fields else card.name)
            return
        terminal = os.get_terminal_size(sys.stdout.fileno())
        width = min(self.options.width, terminal.columns - 12)
        height = min(self.options.height, max(2, terminal.lines - 2))
        if width < 4 or terminal.columns < 24:
            for card in cards:
                print(" ".join(card.fields) + " " + card.name if card.fields else card.name)
            return
        if self.options.long or self.options.one:
            self._rows(cards, width, height, terminal.columns)
        else:
            self._grid(cards, width, height, terminal.columns)
        sys.stdout.flush()

    def _grid(self, cards, width, height, columns):
        # Fixed cells keep filenames and pictures aligned without cursor moves.
        per_row = max(1, (columns - 1) // (width + 3))
        for start in range(0, len(cards), per_row):
            batch = cards[start:start + per_row]
            for card in batch:
                self._image(card, width, height)
            for row in range(height):
                print("   ".join(self._image_row(card, row, width, height) for card in batch))
            labels = []
            for card in batch:
                text = truncate((" ".join(card.fields) + " " if card.fields else "") + card.name, width)
                labels.append(text + " " * (width - wcswidth(text)))
            print("   ".join(labels))
            print()

    def _rows(self, cards, width, height, columns):
        text_width = columns - width - 3
        for card in cards:
            self._image(card, width, height)
            labels = [card.name]
            # Wrap metadata at spaces so narrow terminals do not lose fields.
            if card.fields:
                line = ""
                for word in " ".join(card.fields).split():
                    candidate = (line + " " + word).lstrip()
                    if line and wcswidth(candidate) > text_width:
                        labels.append(line)
                        line = word
                    else:
                        line = candidate
                labels.append(line)
            elif card.dimensions:
                labels.append(card.dimensions)
            start = max(0, (height - len(labels)) // 2)
            count = max(height, len(labels))
            for row in range(count):
                image = self._image_row(card, row, width, height) if row < height else " " * width
                label_index = row - start
                label = labels[label_index] if 0 <= label_index < len(labels) else ""
                print(image + "  " + truncate(label, text_width))
            print()
