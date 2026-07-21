import re


def document_lines(text: str) -> tuple[str, ...]:
    """Split document text into Monaco/LSP lines without visible terminators."""
    return tuple(re.split(r"\r\n|\r|\n", text))


def codepoint_to_utf16(text: str, codepoint: int) -> int:
    if codepoint < 0 or codepoint > len(text):
        raise ValueError("Code-point position is out of bounds")
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text[:codepoint])


def utf16_to_codepoint(text: str, utf16: int) -> int:
    if utf16 < 0:
        raise ValueError("UTF-16 position is out of bounds")

    offset = 0
    for codepoint, character in enumerate(text):
        if offset == utf16:
            return codepoint
        width = 2 if ord(character) > 0xFFFF else 1
        if offset < utf16 < offset + width:
            raise ValueError("UTF-16 position splits a surrogate pair")
        offset += width

    if offset == utf16:
        return len(text)
    raise ValueError("UTF-16 position is out of bounds")
