"""Paragraph-aware chunking with overlap.

Splitting on paragraph boundaries keeps a fact and its qualifier together, which
matters more for answer quality than any embedding-model choice.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{2,}")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def chunk_text(text: str, *, max_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    text = normalize(text)
    if not text:
        return []

    paragraphs = [block.strip() for block in _BLANK_LINES.split(text) if block.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        # A single oversized paragraph still has to be broken up.
        while len(paragraph) > max_chars:
            head, paragraph = paragraph[:max_chars], paragraph[max_chars - overlap_chars :]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)

        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

    if current:
        chunks.append(current)
    return chunks
