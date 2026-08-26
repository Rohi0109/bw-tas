import argparse
import json
import logging

from board.solve_board import setup, solve_board
from board.generate_board import generate_board
from board.parse_board import parse_board
from calculate_damage.set_modifiers import Modifiers



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--board",
        help="Board text as 4 rows, for example ABCD/EFGH/IJKL/MNOP",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    with open("word_dict.json", "r", encoding="utf-8") as f:
        word_dict = json.load(f)
        logging.info("Setup complete!")

    word_counters = setup(word_dict)
    board = parse_board(args.board) if args.board else generate_board()
    logging.info(f"Board\n{board}")
    mod = Modifiers()  # todo: get from user input
    result = solve_board(board, word_dict, word_counters, mod)
    if result is None:
        logging.info("No playable word found.")
        return

    optimal_word, optimal_damage = result
    logging.info(f"Optimal Word: {optimal_word}, Score: {optimal_damage}")


if __name__ == "__main__":
    main()
