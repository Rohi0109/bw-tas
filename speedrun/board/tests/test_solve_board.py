from board.generate_board import Board
from board.solve_board import setup, solve_board
from calculate_damage.set_modifiers import Modifiers


def test_solve_board_uses_letter_counts_only():
    board = Board(
        grid=[
            ["C", "A", "T", "S"],
            ["X", "X", "X", "X"],
            ["X", "X", "X", "X"],
            ["X", "X", "X", "X"],
        ]
    )
    word_dict = {"CAT": 10.0, "CAST": 12.0}

    result = solve_board(board, word_dict, setup(word_dict), Modifiers())

    assert result == ("CAST", 12.0)


def test_solve_board_finds_best_word_by_available_letters():
    board = Board(
        grid=[
            ["C", "A", "R", "T"],
            ["D", "O", "G", "S"],
            ["L", "I", "N", "E"],
            ["P", "U", "M", "B"],
        ]
    )
    word_dict = {"DOG": 5.0, "LINE": 7.0, "CART": 9.0}

    result = solve_board(board, word_dict, setup(word_dict), Modifiers())

    assert result == ("CART", 9.0)
