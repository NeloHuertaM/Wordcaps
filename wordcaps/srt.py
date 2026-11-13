from __future__ import annotations

import re

from .words import MIN_WORD_SECONDS, Word, clean_words

_TIMING = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_TAGS = re.compile(r"<[^>]+>|\{[^}]+\}")
BYTE_ORDER_MARK = chr(0xFEFF)


def _seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000


def _split_cue(text: str, start: float, end: float) -> list[Word]:
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(token) + 1 for token in tokens]
    total = sum(weights)
    span = max(end - start, MIN_WORD_SECONDS)
    words = []
    cursor = start
    for token, weight in zip(tokens, weights):
        length = span * weight / total
        words.append(Word(token, round(cursor, 3), round(cursor + length, 3)))
        cursor += length
    return words


def parse_srt(content: str) -> list[Word]:
    words: list[Word] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.replace(BYTE_ORDER_MARK, "").strip())
    for block in blocks:
        lines = block.strip().splitlines()
        for index, line in enumerate(lines):
            match = _TIMING.search(line)
            if not match:
                continue
            start = _seconds(*match.group(1, 2, 3, 4))
            end = _seconds(*match.group(5, 6, 7, 8))
            text = _TAGS.sub("", " ".join(lines[index + 1:]))
            words.extend(_split_cue(text, start, end))
            break
    return clean_words(words)
