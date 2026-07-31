from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from modelable.rag.model import DocumentationChunk

DEFAULT_TARGET_WORDS = 450
DEFAULT_MAX_WORDS = 700

_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.+?)\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(?P<marker>`{3,}|~{3,})")
_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_ADMONITION_RE = re.compile(r"^\s*(?:!!!|\?\?\?)\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class _Unit:
    kind: str
    text: str


@dataclass(slots=True)
class _Section:
    heading: str | None
    heading_path: list[str]
    anchor: str | None
    units: list[_Unit]


def chunk_markdown(
    content: str,
    *,
    source_path: str,
    url: str,
    language: str = "en",
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[DocumentationChunk]:
    if target_words <= 0 or max_words <= 0 or target_words > max_words:
        raise ValueError("target_words and max_words must be positive, with target_words <= max_words")

    normalized_source_path = _normalize_source_path(source_path)
    sections, title = _parse_sections(content)
    document_title = title or Path(normalized_source_path).stem
    chunks: list[DocumentationChunk] = []

    for section in sections:
        if not section.units:
            continue
        units = _expand_oversized_units(section.units, max_words)
        pending: list[_Unit] = []
        pending_words = 0
        parts: list[str] = []

        for unit in units:
            unit_words = _word_count(unit.text)
            if pending and pending_words + unit_words > target_words:
                parts.append(_render_chunk(section.heading_path, pending))
                pending = []
                pending_words = 0
            pending.append(unit)
            pending_words += unit_words
        if pending:
            parts.append(_render_chunk(section.heading_path, pending))

        for part_number, part in enumerate(parts, start=1):
            external_id = _part_external_id(normalized_source_path, section.anchor, part_number)
            chunks.append(
                DocumentationChunk(
                    external_id=external_id,
                    source_path=normalized_source_path,
                    url=url,
                    language=language,
                    title=document_title,
                    heading=section.heading,
                    heading_path=list(section.heading_path),
                    content=part,
                    chunk_index=len(chunks),
                )
            )

    return chunks


def discover_markdown_files(source: Path) -> list[Path]:
    if not source.is_dir():
        raise ValueError(f"documentation source must be a directory: {source}")
    return sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() == ".md"),
        key=lambda path: path.relative_to(source).as_posix(),
    )


def load_documentation_chunks(
    source: Path,
    *,
    base_url: str | None = None,
    language: str = "en",
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[DocumentationChunk]:
    chunks: list[DocumentationChunk] = []
    for path in discover_markdown_files(source):
        relative_path = path.relative_to(source).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"invalid UTF-8 Markdown input: {path}") from error
        url = relative_path if base_url is None else f"{base_url.rstrip('/')}/{relative_path}"
        chunks.extend(
            chunk_markdown(
                content,
                source_path=relative_path,
                url=url,
                language=language,
                target_words=target_words,
                max_words=max_words,
            )
        )
    return chunks


def _parse_sections(content: str) -> tuple[list[_Section], str | None]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = [_Section(heading=None, heading_path=[], anchor=None, units=[])]
    heading_stack: list[tuple[int, str]] = []
    used_anchors: dict[str, int] = {}
    title: str | None = None
    buffer: list[str] = []
    index = 0

    def flush_buffer(kind: str = "paragraph") -> None:
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                sections[-1].units.append(_Unit(kind=kind, text=text))
            buffer.clear()

    while index < len(lines):
        line = lines[index]
        fence = _FENCE_RE.match(line)
        if fence:
            flush_buffer()
            marker = fence.group("marker")
            fence_lines = [line]
            index += 1
            while index < len(lines):
                fence_lines.append(lines[index])
                if _is_closing_fence(lines[index], marker):
                    index += 1
                    break
                index += 1
            sections[-1].units.append(_Unit(kind="fence", text="\n".join(fence_lines).strip()))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_buffer()
            level = len(heading.group("marks"))
            heading_text = re.sub(r"\s+#+\s*$", "", heading.group("text")).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
            if level == 1 and title is None:
                title = heading_text
            base_anchor = _slugify(heading_text) or "section"
            occurrence = used_anchors.get(base_anchor, 0) + 1
            used_anchors[base_anchor] = occurrence
            anchor = base_anchor if occurrence == 1 else f"{base_anchor}-{occurrence}"
            sections.append(
                _Section(
                    heading=heading_text,
                    heading_path=[text for _, text in heading_stack],
                    anchor=anchor,
                    units=[],
                )
            )
            index += 1
            continue

        if not line.strip():
            flush_buffer()
            index += 1
            continue

        if _is_table_start(lines, index):
            flush_buffer()
            table_lines = [line]
            index += 1
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                table_lines.append(lines[index])
                index += 1
            sections[-1].units.append(_Unit(kind="table", text="\n".join(table_lines).strip()))
            continue

        if _LIST_RE.match(line):
            flush_buffer()
            list_lines = [line]
            index += 1
            while index < len(lines) and (_LIST_RE.match(lines[index]) or lines[index].startswith((" ", "\t"))):
                list_lines.append(lines[index])
                index += 1
            sections[-1].units.append(_Unit(kind="list", text="\n".join(list_lines).strip()))
            continue

        if _BLOCKQUOTE_RE.match(line) or _ADMONITION_RE.match(line):
            flush_buffer()
            block_lines = [line]
            index += 1
            while (
                index < len(lines)
                and lines[index].strip()
                and (_BLOCKQUOTE_RE.match(lines[index]) or lines[index].startswith((" ", "\t")))
            ):
                block_lines.append(lines[index])
                index += 1
            sections[-1].units.append(_Unit(kind="blockquote", text="\n".join(block_lines).strip()))
            continue

        buffer.append(line)
        index += 1

    flush_buffer()
    return sections, title


def _expand_oversized_units(units: list[_Unit], max_words: int) -> list[_Unit]:
    expanded: list[_Unit] = []
    for unit in units:
        if unit.kind != "paragraph" or _word_count(unit.text) <= max_words:
            expanded.append(unit)
            continue
        sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(unit.text) if sentence.strip()]
        if not sentences:
            expanded.append(unit)
            continue
        sentence_buffer: list[str] = []
        sentence_words = 0
        for sentence in sentences:
            words = _word_count(sentence)
            if sentence_buffer and sentence_words + words > max_words:
                expanded.append(_Unit(kind="paragraph", text=" ".join(sentence_buffer)))
                sentence_buffer = []
                sentence_words = 0
            sentence_buffer.append(sentence)
            sentence_words += words
        if sentence_buffer:
            expanded.append(_Unit(kind="paragraph", text=" ".join(sentence_buffer)))
    return expanded


def _render_chunk(heading_path: list[str], units: list[_Unit]) -> str:
    body = "\n\n".join(unit.text for unit in units)
    if not heading_path:
        return body
    return f"Heading path: {' > '.join(heading_path)}\n\n{body}"


def _part_external_id(source_path: str, anchor: str | None, part_number: int) -> str:
    base = source_path if anchor is None else f"{source_path}#{anchor}"
    if part_number == 1:
        return base
    return f"{base}-part-{part_number}"


def _is_closing_fence(line: str, marker: str) -> bool:
    closing = _FENCE_RE.match(line)
    return bool(closing and closing.group("marker")[0] == marker[0] and len(closing.group("marker")) >= len(marker))


def _is_table_start(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and "|" in lines[index] and bool(_TABLE_SEPARATOR_RE.match(lines[index + 1]))


def _slugify(value: str) -> str:
    value = re.sub(r"[`*_~]", "", value.casefold())
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _normalize_source_path(source_path: str) -> str:
    return source_path.replace("\\", "/").lstrip("./")


def _word_count(value: str) -> int:
    return len(value.split())
