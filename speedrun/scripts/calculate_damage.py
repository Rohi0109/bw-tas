import json

from word.word import Word

word_dict = {}


def add_damage_to_word_list(path: str):
    with open(path, "r") as file:
        for f in file:
            word = Word(f)
            word_dict[word.word_name] = word.base_damage

    with open("word_dict.json", "w") as json_file:
        json.dump(word_dict, json_file, indent=4)


if __name__ == "__main__":
    add_damage_to_word_list("word/words.txt")
