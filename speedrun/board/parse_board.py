from board.generate_board import Board


def parse_board(board_text: str) -> Board:
    rows = [
        row.strip().replace(" ", "").upper()
        for row in board_text.strip().replace("/", "\n").splitlines()
        if row.strip()
    ]
    if len(rows) != 4:
        raise ValueError("Board must contain exactly 4 rows.")

    grid: list[list[str]] = []
    for row in rows:
        if len(row) != 4:
            raise ValueError("Each board row must contain exactly 4 letters.")
        if not row.isalpha():
            raise ValueError("Board rows may only contain letters.")
        grid.append(list(row))

    return Board(grid=grid)
