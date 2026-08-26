from board.generate_board import Board, generate_board


def test_generate_board():
    board = generate_board()
    assert isinstance(board, Board)
    assert len(board.grid) == 4
    assert all(len(row) == 4 for row in board.grid)
