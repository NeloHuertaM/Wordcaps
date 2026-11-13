from __future__ import annotations

import re
from dataclasses import dataclass, field, fields

from .animations import ANIMATIONS, hold_then_switch, size_keys
from .words import Word

_SENTENCE_END = re.compile(r"[.!?…]$")
_STRIP_PUNCTUATION = re.compile(r"[^\w'’\-]", re.UNICODE)
_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")
_CLIP_COLORS = {"Orange", "Apricot", "Yellow", "Lime", "Olive", "Green", "Teal", "Navy",
                "Blue", "Purple", "Violet", "Pink", "Tan", "Beige", "Brown", "Chocolate"}

MODE_ACCUMULATE = "accumulate"
MODE_SINGLE = "single"
MODES = (MODE_ACCUMULATE, MODE_SINGLE)

EMPHASIS_NONE = "none"
EMPHASIS_LONGEST = "longest"
EMPHASIS_KEYWORDS = "keywords"
EMPHASES = (EMPHASIS_NONE, EMPHASIS_LONGEST, EMPHASIS_KEYWORDS)

LONGEST_EMPHASIS_MIN_CHARS = 5
DEFAULT_SPACE_WIDTH = 0.3
SIZE_INPUT = "Size"
FILL_ELEMENT = 1
OUTLINE_ELEMENT = 2

_NUMERIC_SETTINGS = ("max_words", "max_chars_per_line", "max_lines", "pause_split", "size", "emphasis_scale",
                     "zone_y", "zone_width", "outline_thickness", "hold_seconds", "char_width", "line_spacing")


@dataclass
class CaptionSettings:
    mode: str = MODE_ACCUMULATE
    max_words: int = 3
    max_chars_per_line: int = 16
    max_lines: int = 2
    pause_split: float = 0.45
    split_on_punctuation: bool = True
    uppercase: bool = True
    strip_punctuation: bool = False
    font: str = "Montserrat"
    font_style: str = "Black"
    size: float = 0.08
    emphasis: str = EMPHASIS_LONGEST
    keywords: list[str] = field(default_factory=list)
    emphasis_scale: float = 1.35
    zone_y: float = 0.3
    zone_width: float = 0.8
    color: str = "#ffffff"
    highlight_color: str = "#ffd400"
    highlight_active: bool = True
    outline: bool = True
    outline_color: str = "#000000"
    outline_thickness: float = 0.06
    animation: str = "pop"
    emphasis_animation: str = "bounce"
    hold_seconds: float = 0.15
    char_width: float = 0.62
    glyph_widths: dict[str, float] = field(default_factory=dict)
    line_spacing: float = 1.15
    clip_color: str = "Orange"

    def text_width(self, text: str, size: float) -> float:
        return sum(float(self.glyph_widths.get(ch, self.char_width)) for ch in text) * size

    def word_gap(self, size: float) -> float:
        return float(self.glyph_widths.get(" ", DEFAULT_SPACE_WIDTH)) * size

    @staticmethod
    def from_dict(data: dict | None) -> "CaptionSettings":
        known = {f.name for f in fields(CaptionSettings)}
        settings = CaptionSettings(**{k: v for k, v in (data or {}).items() if k in known})
        settings.validate()
        return settings

    def validate(self) -> None:
        for name in _NUMERIC_SETTINGS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} debe ser un número.")
        if self.mode not in MODES:
            raise ValueError(f"Modo desconocido: {self.mode}")
        if self.emphasis not in EMPHASES:
            raise ValueError(f"Énfasis desconocido: {self.emphasis}")
        for name in (self.animation, self.emphasis_animation):
            if name not in ANIMATIONS:
                raise ValueError(f"Animación desconocida: {name}")
        for color in (self.color, self.highlight_color, self.outline_color):
            hex_to_rgb(color)
        if self.clip_color not in _CLIP_COLORS:
            raise ValueError(f"Color de clip no válido en Resolve: {self.clip_color}")
        if self.max_words < 1 or self.max_lines < 1 or self.max_chars_per_line < 1:
            raise ValueError("Palabras por grupo, líneas y caracteres por línea deben ser al menos 1.")
        if not 0 < self.size < 1:
            raise ValueError("El tamaño debe estar entre 0 y 1.")
        if not isinstance(self.glyph_widths, dict) or not isinstance(self.keywords, list):
            raise ValueError("glyph_widths debe ser un objeto y keywords una lista.")
        if any(len(ch) != 1 or not 0 <= float(w) < 5 for ch, w in self.glyph_widths.items()):
            raise ValueError("Los anchos de letra medidos no son válidos.")


@dataclass(frozen=True)
class Frame:
    fps: float
    width: int
    height: int
    start_frame: int
    end_frame: int

    @staticmethod
    def from_timeline(info: dict) -> "Frame":
        try:
            frame = Frame(
                fps=float(info["fps"]),
                width=int(info["width"]),
                height=int(info["height"]),
                start_frame=int(info["startFrame"]),
                end_frame=int(info["endFrame"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"El timeline no informa fps, resolución o duración válidos ({error!r})."
            ) from error
        if frame.fps <= 0 or frame.width <= 0 or frame.height <= 0:
            raise ValueError("El timeline tiene fps o resolución a cero.")
        return frame

    def to_frame(self, seconds: float) -> int:
        return self.start_frame + round(seconds * self.fps)


@dataclass
class PlacedWord:
    word: Word
    text: str
    emphasis: bool
    size: float
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0


@dataclass
class Group:
    words: list[PlacedWord]
    end: float = 0.0

    @property
    def start(self) -> float:
        return self.words[0].word.start


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    match = _HEX_COLOR.match(color.strip()) if isinstance(color, str) else None
    if not match:
        raise ValueError(f"Color no válido: {color}")
    value = match.group(1)
    return tuple(round(int(value[i:i + 2], 16) / 255, 4) for i in (0, 2, 4))


def display_text(text: str, settings: CaptionSettings) -> str:
    if settings.strip_punctuation:
        text = _STRIP_PUNCTUATION.sub("", text) or text
    return text.upper() if settings.uppercase else text


def _normalized(text: str) -> str:
    return _STRIP_PUNCTUATION.sub("", text).lower()


def _starts_new_group(group: list[Word], word: Word, settings: CaptionSettings) -> bool:
    if not group:
        return False
    if settings.mode == MODE_SINGLE or len(group) >= settings.max_words:
        return True
    previous = group[-1]
    if word.start - previous.end > settings.pause_split:
        return True
    if settings.split_on_punctuation and _SENTENCE_END.search(previous.text):
        return True
    candidate = _sized_words(group + [word], settings)
    return len(_wrap_rows(candidate, settings)) > settings.max_lines


def split_groups(words: list[Word], settings: CaptionSettings) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if _starts_new_group(current, word, settings):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _emphasis_flags(group: list[Word], settings: CaptionSettings) -> list[bool]:
    if settings.emphasis == EMPHASIS_KEYWORDS:
        keywords = {_normalized(k) for k in settings.keywords if k.strip()}
        return [_normalized(w.text) in keywords for w in group]
    if settings.emphasis == EMPHASIS_LONGEST and len(group) > 1:
        lengths = [len(_normalized(w.text)) for w in group]
        longest = max(lengths)
        if longest >= LONGEST_EMPHASIS_MIN_CHARS:
            first = lengths.index(longest)
            return [i == first for i in range(len(group))]
    return [False] * len(group)


def _sized_words(words: list[Word], settings: CaptionSettings) -> list[PlacedWord]:
    placed = []
    for word, flag in zip(words, _emphasis_flags(words, settings)):
        text = display_text(word.text, settings)
        size = round(settings.size * (settings.emphasis_scale if flag else 1.0), 5)
        placed.append(PlacedWord(word=word, text=text, emphasis=flag, size=size,
                                 width=settings.text_width(text, size)))
    return placed


def _wrap_rows(placed: list[PlacedWord], settings: CaptionSettings) -> list[list[PlacedWord]]:
    rows: list[list[PlacedWord]] = [[]]
    row_width = 0.0
    row_chars = 0
    for item in placed:
        gap = settings.word_gap(item.size) if rows[-1] else 0.0
        too_wide = row_width + gap + item.width > settings.zone_width
        too_long = row_chars + len(item.text) + (1 if rows[-1] else 0) > settings.max_chars_per_line
        if rows[-1] and (too_wide or too_long):
            rows.append([])
            row_width, row_chars, gap = 0.0, 0, 0.0
        rows[-1].append(item)
        row_width += gap + item.width
        row_chars += len(item.text) + (1 if len(rows[-1]) > 1 else 0)
    return rows


def _place_group(words: list[Word], settings: CaptionSettings, frame: Frame) -> Group:
    placed = _sized_words(words, settings)
    rows = _wrap_rows(placed, settings)
    aspect = frame.width / frame.height
    heights = [max(i.size for i in row) * aspect * settings.line_spacing for row in rows]
    top = settings.zone_y + sum(heights) / 2
    for row, height in zip(rows, heights):
        center_y = top - height / 2
        total = sum(i.width for i in row) + sum(settings.word_gap(i.size) for i in row[1:])
        cursor = 0.5 - total / 2
        for index, item in enumerate(row):
            if index:
                cursor += settings.word_gap(item.size)
            item.x = round(cursor + item.width / 2, 5)
            item.y = round(center_y, 5)
            cursor += item.width
        top -= height
    return Group(words=placed)


def build_groups(words: list[Word], settings: CaptionSettings, frame: Frame) -> list[Group]:
    ordered = sorted(words, key=lambda w: (w.start, w.end))
    groups = [_place_group(g, settings, frame) for g in split_groups(ordered, settings)]
    for index, group in enumerate(groups):
        end = group.words[-1].word.end + settings.hold_seconds
        if index + 1 < len(groups):
            end = min(end, groups[index + 1].start)
        group.end = max(end, group.start)
    return groups


def _color_channels(element: int) -> tuple[str, str, str]:
    return f"Red{element}", f"Green{element}", f"Blue{element}"


def _color_inputs(element: int, rgb: tuple[float, float, float]) -> dict:
    return dict(zip(_color_channels(element), rgb))


def _clip_for(item: PlacedWord, lane: int, record: int, finish: int, settings: CaptionSettings, frame: Frame) -> dict:
    duration = finish - record
    base = hex_to_rgb(settings.color)
    highlight = hex_to_rgb(settings.highlight_color)

    inputs = {
        "StyledText": item.text,
        "Font": settings.font,
        "Style": settings.font_style,
        SIZE_INPUT: item.size,
        "Center": [item.x, item.y],
    }
    if settings.outline:
        inputs.update({f"Enabled{OUTLINE_ELEMENT}": 1, f"Thickness{OUTLINE_ELEMENT}": settings.outline_thickness})
        inputs.update(_color_inputs(OUTLINE_ELEMENT, hex_to_rgb(settings.outline_color)))

    keys = []
    animation = settings.emphasis_animation if item.emphasis else settings.animation
    size_points = size_keys(animation, item.size, duration)
    if size_points:
        keys.append({"input": SIZE_INPUT, "points": size_points})

    if item.emphasis:
        inputs.update(_color_inputs(FILL_ELEMENT, highlight))
    elif settings.highlight_active and settings.mode == MODE_ACCUMULATE:
        active = frame.to_frame(item.word.end) - record
        if active >= duration:
            inputs.update(_color_inputs(FILL_ELEMENT, highlight))
        else:
            inputs.update(_color_inputs(FILL_ELEMENT, base))
            for channel, first, second in zip(_color_channels(FILL_ELEMENT), highlight, base):
                keys.append({"input": channel, "points": hold_then_switch(first, second, active)})
    else:
        inputs.update(_color_inputs(FILL_ELEMENT, base))

    return {
        "text": item.text,
        "record": record,
        "duration": duration,
        "lane": lane,
        "inputs": inputs,
        "keys": keys,
        "clipColor": settings.clip_color,
    }


def build_clips(words: list[Word], settings: CaptionSettings, frame: Frame) -> dict:
    groups = build_groups(words, settings, frame)
    clips = []
    lane_free_from: dict[int, int] = {}
    for group in groups:
        finish = min(frame.to_frame(group.end), frame.end_frame)
        for lane, item in enumerate(group.words, start=1):
            record = max(frame.to_frame(item.word.start), lane_free_from.get(lane, frame.start_frame))
            if record >= finish:
                continue
            clips.append(_clip_for(item, lane, record, finish, settings, frame))
            lane_free_from[lane] = finish
    lanes = max((c["lane"] for c in clips), default=0)
    preview = [
        {
            "start": g.start,
            "end": g.end,
            "words": [
                {"text": w.text, "x": w.x, "y": w.y, "size": w.size, "emphasis": w.emphasis,
                 "start": w.word.start, "end": w.word.end}
                for w in g.words
            ],
        }
        for g in groups
    ]
    return {"clips": clips, "lanes": lanes, "groups": preview}
