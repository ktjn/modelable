import pytest

from modelable.language.positions import codepoint_to_utf16, utf16_to_codepoint


@pytest.mark.parametrize(
    ("text", "codepoint", "utf16"),
    [("customer", 4, 4), ("a😀b", 2, 3), ("😀name", 1, 2)],
)
def test_codepoint_utf16_round_trip(text: str, codepoint: int, utf16: int) -> None:
    assert codepoint_to_utf16(text, codepoint) == utf16
    assert utf16_to_codepoint(text, utf16) == codepoint


def test_utf16_rejects_half_surrogate_position() -> None:
    with pytest.raises(ValueError, match="surrogate"):
        utf16_to_codepoint("😀", 1)


@pytest.mark.parametrize("codepoint", [-1, 4])
def test_codepoint_rejects_out_of_bounds_position(codepoint: int) -> None:
    with pytest.raises(ValueError, match="bounds"):
        codepoint_to_utf16("abc", codepoint)


@pytest.mark.parametrize("utf16", [-1, 5])
def test_utf16_rejects_out_of_bounds_position(utf16: int) -> None:
    with pytest.raises(ValueError, match="bounds"):
        utf16_to_codepoint("a😀b", utf16)
