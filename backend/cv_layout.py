"""Generic, geometry-only reconstruction of positioned PDF text for CV extraction."""

from dataclasses import dataclass, field
from io import BytesIO
from statistics import median
from typing import Any

import pdfplumber

CURRENT_CV_PARSER_VERSION = "layout_v3"


class LayoutExtractionError(Exception):
    pass


@dataclass(frozen=True)
class LayoutWord:
    page: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float
    font: str


@dataclass
class LayoutLine:
    page: int
    words: list[LayoutWord]
    x0: float = field(init=False)
    x1: float = field(init=False)
    top: float = field(init=False)
    bottom: float = field(init=False)
    text: str = field(init=False)
    size: float = field(init=False)
    font: str = field(init=False)

    def __post_init__(self):
        self.words.sort(key=lambda word: word.x0)
        self.x0, self.x1 = self.words[0].x0, self.words[-1].x1
        self.top, self.bottom = min(word.top for word in self.words), max(word.bottom for word in self.words)
        self.text = " ".join(word.text for word in self.words).strip()
        self.size = median(word.size for word in self.words)
        self.font = self.words[0].font


@dataclass
class LayoutBlock:
    id: str
    page: int
    lines: list[LayoutLine]
    x0: float = field(init=False)
    x1: float = field(init=False)
    top: float = field(init=False)
    bottom: float = field(init=False)
    text: str = field(init=False)
    size: float = field(init=False)

    def __post_init__(self):
        self.x0, self.x1 = min(line.x0 for line in self.lines), max(line.x1 for line in self.lines)
        self.top, self.bottom = min(line.top for line in self.lines), max(line.bottom for line in self.lines)
        self.text = "\n".join(line.text for line in self.lines)
        self.size = median(line.size for line in self.lines)


@dataclass(frozen=True)
class LayoutExtractionResult:
    parser_version: str
    model_text: str
    plain_text: str
    layout_confidence: str
    warnings: list[str]
    metadata: dict[str, Any]


def _line_words(words: list[LayoutWord]) -> list[LayoutLine]:
    lines: list[list[LayoutWord]] = []
    for word in sorted(words, key=lambda item: (item.page, item.top, item.x0)):
        placed = False
        for candidate in reversed(lines):
            first = candidate[0]
            if first.page != word.page:
                break
            baseline = median(item.top for item in candidate)
            tolerance = max(2.0, median(item.size for item in candidate) * 0.38)
            if abs(word.top - baseline) <= tolerance:
                candidate.append(word)
                placed = True
                break
            if word.top - baseline > tolerance * 2:
                break
        if not placed:
            lines.append([word])
    result: list[LayoutLine] = []
    for items in lines:
        ordered = sorted(items, key=lambda word: word.x0)
        segments: list[list[LayoutWord]] = [[ordered[0]]]
        for word in ordered[1:]:
            previous = segments[-1][-1]
            # Large same-baseline whitespace is a visual region boundary, not
            # normal word spacing.  The threshold is derived from font size.
            if word.x0 - previous.x1 > max(42.0, median(item.size for item in ordered) * 4.5):
                segments.append([word])
            else:
                segments[-1].append(word)
        result.extend(LayoutLine(page=segment[0].page, words=segment) for segment in segments)
    return result


def _blocks(lines: list[LayoutLine]) -> list[LayoutBlock]:
    grouped: list[list[LayoutLine]] = []
    for line in sorted(lines, key=lambda item: (item.page, item.top, item.x0)):
        best: list[LayoutLine] | None = None
        for candidate in reversed(grouped):
            previous = candidate[-1]
            if previous.page != line.page:
                break
            vertical_gap = line.top - previous.bottom
            alignment = abs(line.x0 - previous.x0)
            max_gap = max(8.0, median(item.bottom - item.top for item in candidate) * 1.8)
            if 0 <= vertical_gap <= max_gap and alignment <= max(18.0, previous.size * 2.0):
                best = candidate
                break
        if best is None:
            grouped.append([line])
        else:
            best.append(line)
    counters: dict[int, int] = {}
    result: list[LayoutBlock] = []
    for group in grouped:
        page = group[0].page
        counters[page] = counters.get(page, 0) + 1
        result.append(LayoutBlock(id=f"p{page}-b{counters[page]}", page=page, lines=group))
    return result


def _heading(block: LayoutBlock, page_median: float) -> bool:
    compact = " ".join(block.text.split())
    letters = [character for character in compact if character.isalpha()]
    upper_ratio = sum(character.isupper() for character in letters) / len(letters) if letters else 0
    bold = any("bold" in line.font.lower() for line in block.lines)
    return len(compact) <= 70 and (block.size >= page_median * 1.18 or bold or upper_ratio >= 0.78)


def _overlap_ratio(first: LayoutBlock, second: LayoutBlock) -> float:
    overlap = max(0.0, min(first.bottom, second.bottom) - max(first.top, second.top))
    return overlap / max(1.0, min(first.bottom - first.top, second.bottom - second.top))


def _render_page(page: int, blocks: list[LayoutBlock]) -> tuple[list[str], int]:
    if not blocks:
        return [f"[PAGE {page}]"], 0
    page_median = median(block.size for block in blocks)
    result = [f"[PAGE {page}]"]
    used: set[str] = set()
    regions = 1
    for block in sorted(blocks, key=lambda item: (item.top, item.x0)):
        if block.id in used:
            continue
        if _heading(block, page_median):
            result.extend([f"[SECTION {block.id}]", block.text, "[/SECTION]"])
            used.add(block.id)
            regions += 1
            continue
        peers = [other for other in blocks if other.id not in used and other.id != block.id and _overlap_ratio(block, other) >= 0.35 and (other.x0 >= block.x1 or block.x0 >= other.x1)]
        if peers:
            row = sorted([block, *peers], key=lambda item: item.x0)
            result.append(f"[ROW {block.id}]")
            if len(row) == 2 and (len(row[0].lines) > 1 or len(row[1].lines) > 1):
                _render_nested_line_pairs(result, row[0], row[1])
            else:
                for index, item in enumerate(row):
                    label = "LEFT" if index == 0 else "RIGHT" if index == 1 else f"COLUMN {index + 1}"
                    result.extend([f"{label} ({item.id}):", item.text])
            for item in row:
                used.add(item.id)
            result.append("[/ROW]")
        else:
            result.extend([f"[BLOCK {block.id}]", block.text, "[/BLOCK]"])
            used.add(block.id)
    return result, regions


def _render_nested_line_pairs(result: list[str], left: LayoutBlock, right: LayoutBlock) -> None:
    """Pair aligned child lines in visual label/value blocks, without semantics."""
    unused_right = set(range(len(right.lines)))
    pairs: list[tuple[LayoutLine | None, LayoutLine | None]] = []
    for left_index, left_line in enumerate(left.lines):
        candidates = [index for index in unused_right if abs((right.lines[index].top + right.lines[index].bottom) / 2 - (left_line.top + left_line.bottom) / 2) <= max(10.0, left_line.size * 1.8)]
        if candidates:
            right_index = min(candidates, key=lambda index: abs(right.lines[index].top - left_line.top))
            unused_right.remove(right_index)
            pairs.append((left_line, right.lines[right_index]))
        else:
            pairs.append((left_line, None))
    pairs.extend((None, right.lines[index]) for index in sorted(unused_right))
    for index, (left_line, right_line) in enumerate(pairs, start=1):
        result.append(f"[LINE_ROW {left.id}-l{index}]")
        if left_line:
            result.extend([f"LEFT ({left.id}):", left_line.text])
        if right_line:
            result.extend([f"RIGHT ({right.id}):", right_line.text])
        result.append("[/LINE_ROW]")


def layout_diagnostic(data: bytes) -> dict[str, int | str | bool]:
    """Safe structural summary for local developer diagnostics; never returns CV text."""
    result = reconstruct_pdf(data)
    return {
        "parser_version": result.parser_version,
        "pages": result.metadata["pages"],
        "blocks": result.metadata["blocks"],
        "sections": result.model_text.count("[SECTION"),
        "rows": result.model_text.count("[ROW "),
        "line_rows": result.model_text.count("[LINE_ROW "),
        "fallback_used": result.metadata["fallback_used"],
    }


def reconstruct_pdf(data: bytes) -> LayoutExtractionResult:
    """Extract words with geometry and render a compact, model-oriented context."""
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            pages = list(pdf.pages)
            words: list[LayoutWord] = []
            plain_pages: list[str] = []
            for page_number, page in enumerate(pages, start=1):
                raw_words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=False, keep_blank_chars=False)
                plain_pages.append(page.extract_text() or "")
                for item in raw_words:
                    text = str(item.get("text", "")).strip()
                    if text:
                        words.append(LayoutWord(page_number, text, float(item["x0"]), float(item["top"]), float(item["x1"]), float(item["bottom"]), float(item.get("size") or 10), str(item.get("fontname") or "")))
    except Exception as error:
        raise LayoutExtractionError("Positioned PDF text extraction was unavailable.") from error
    if not words:
        raise LayoutExtractionError("No positioned PDF text was available.")
    lines = _line_words(words)
    blocks = _blocks(lines)
    rendered: list[str] = []
    region_count = 0
    for page in range(1, len(pages) + 1):
        page_rendered, page_regions = _render_page(page, [block for block in blocks if block.page == page])
        rendered.extend(page_rendered)
        region_count += page_regions
    confidence = "high" if len(blocks) >= 3 else "medium"
    return LayoutExtractionResult(CURRENT_CV_PARSER_VERSION, "\n".join(rendered), "\n".join(plain_pages), confidence, [], {"pages": len(pages), "blocks": len(blocks), "layout_regions": region_count, "fallback_used": False})
