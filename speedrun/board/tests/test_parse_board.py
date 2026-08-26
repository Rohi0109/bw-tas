import pytest

from board.parse_board import parse_board


def test_parse_board_accepts_slashes():
    board = parse_board("abcd/efgh/ijkl/mnop")
    assert board.grid == [
        ["A", "B", "C", "D"],
        ["E", "F", "G", "H"],
        ["I", "J", "K", "L"],
        ["M", "N", "O", "P"],
    ]


def test_parse_board_rejects_bad_shape():
    with pytest.raises(ValueError):
        parse_board("abc/def/ghi")
