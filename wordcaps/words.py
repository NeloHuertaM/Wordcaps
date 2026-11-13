from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_PUNCTUATION_ONLY = re.compile(r"^[\s\.,;:!?¡¿…\"'«»\-–)\]]+$")
_NON_SPEECH = re.compile(r"^\s*[\[\(].*[\]\)]\s*$")
MIN_WORD_SECONDS = 0.05


@dataclass
class Word:
    text: str
    start: float
    end: float

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Word":
        return Word(text=str(data["text"]), start=float(data["start"]), end=float(data["end"]))


def clean_words(raw: list[Word]) -> list[Word]:
    words: list[Word] = []
    for word in raw:
        text = word.text.strip()
        if not text or _NON_SPEECH.match(text):
            continue
        if _PUNCTUATION_ONLY.match(text) and words:
            previous = words[-1]
            words[-1] = Word(previous.text + text, previous.start, max(previous.end, word.end))
            continue
        end = word.end if word.end > word.start else word.start + MIN_WORD_SECONDS
        words.append(Word(text, word.start, end))
    return words
