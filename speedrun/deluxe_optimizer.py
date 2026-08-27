"""Exact-state Chapter 1 optimizer for Bookworm Adventures Deluxe TAS runs."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


CONTEXT_RE = re.compile(
    r"AUTOMATION_CONTEXT=(?P<seq>\d+)\|(?P<book>-?\d+)\|"
    r"(?P<chapter>-?\d+)\|(?P<stage>-?\d+)\|E"
)
ENEMY_RE = re.compile(r"AUTOMATION_ENEMY=(?P<seq>\d+)\|(?P<value>[^|]+)\|E")
HEALTH_RE = re.compile(
    r"AUTOMATION_HEALTH=(?P<seq>\d+)\|(?P<hp>-?\d+(?:\.\d+)?)\|"
    r"(?P<max_hp>-?\d+(?:\.\d+)?)\|(?P<offense>-?\d+(?:\.\d+)?)\|E"
)
PLAYER_HEALTH_RE = re.compile(
    r"AUTOMATION_PLAYER_HEALTH=(?P<seq>\d+)\|"
    r"(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)\|E"
)
LETTERS_RE = re.compile(
    r"AUTOMATION_LETTERS=(?P<seq>\d+)\|(?P<row>[0-3])\|(?P<value>[A-Z]{4})\|E"
)
GEMS_RE = re.compile(
    r"AUTOMATION_GEMS=(?P<seq>\d+)\|(?P<row>[0-3])\|(?P<value>[a-z](?:,[a-z]){3})\|E"
)
POWERS_RE = re.compile(
    r"AUTOMATION_POWERS=(?P<seq>\d+)\|(?P<row>[0-3])\|"
    r"(?P<value>-?\d+(?:\.\d+)?(?:,-?\d+(?:\.\d+)?){3})\|E"
)
SELECTABLE_RE = re.compile(
    r"AUTOMATION_SELECTABLE=(?P<seq>\d+)\|(?P<row>[0-3])\|"
    r"(?P<value>[01]{4})\|E"
)
MODS_RE = re.compile(r"AUTOMATION_MODS=(?P<seq>\d+)\|(?P<value>[^|]+)\|E")
OVERKILL_RE = re.compile(
    r"AUTOMATION_OVERKILL=(?P<seq>\d+)\|"
    r"(?P<value>none|-?\d+(?:\.\d+)?(?:,-?\d+(?:\.\d+)?)*)\|E"
)
READY_SEQ_RE = re.compile(r"AUTOMATION_READY_SEQ=(?P<seq>\d+)\|E")
GEM_CODE_NAMES = {
    "n": "none", "a": "amethyst", "s": "sapphire", "e": "emerald",
    "g": "garnet", "r": "ruby", "c": "crystal", "d": "diamond",
    "m": "metal",
}

DAMAGE_BY_LENGTH = {
    3: 0.25, 4: 0.5, 5: 0.75, 6: 1.0, 7: 1.5, 8: 2.0,
    9: 2.75, 10: 3.5, 11: 4.5, 12: 5.5, 13: 6.75,
    14: 8.0, 15: 9.5, 16: 11.0,
}

GEM_TIER_NAMES = (
    "amethyst", "sapphire", "emerald", "garnet", "ruby", "crystal", "diamond"
)

SUPPORTED_DAMAGE_TREASURES = {
    "artemis bow", "arch of xyzzy", "heph's hammer",
    "hand of hercules", "wooden parrot",
}

BOOK1_MIN_KILL_ENEMIES = frozenset({
    "trojanspearman", "trojanwarrior", "warhound", "trojancaptain",
    "alexander", "polydamas", "mountaingoat", "ewe", "cyclopsherder",
    "angryram", "cyclopswarrior", "polyphemus", "seaserpent", "siren",
    "seawitch", "seaelemental", "kraken", "scylla", "charybdis",
    "enchantedhound", "enchantedeagle", "enchantedlion", "enchantedram",
    "enchantedscorpion", "enchantedserpent", "circe", "shade", "specter",
    "banshee", "phantom", "manes", "orthrus", "cerberus",
})

# Shipped roster identifiers and localized/live display text are not always
# the same name. Keep exceptional mappings explicit and auditable; structural
# decorations such as "(Boss)" and Hydra phases are handled below.
DISPLAY_NAME_ALIASES = {
    "calydonianboar": "caledonianboar",
    "bronzestymphalian": "stymphalianbirdbronze",
    "steelstymphalian": "stymphalianbirdsteel",
    "centaurgrappler": "centaurwarrior",
    "centaurhunter": "centaurarcher",
    "limniad": "helead",
    "lesserbasilisk": "basilisk",
}


def _normal_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _roster_name(value: str) -> str:
    """Normalize Deluxe's decorated display names to roster identifiers."""
    normalized = _normal_name(value)
    if normalized.startswith("angry"):
        normalized = normalized[len("angry"):]
    if normalized.endswith("boss"):
        normalized = normalized[:-len("boss")]
    if re.fullmatch(r"hydra(?:head\d+|mainhead)", normalized):
        normalized = "hydra"
    return DISPLAY_NAME_ALIASES.get(normalized, normalized)


def load_chapter1_hp_map() -> dict[str, int | tuple[int, ...]]:
    root = Path(__file__).resolve().parents[1]
    roster_path = root / "BookwormAdventuresModding/bwakit/game/data/enemy_rosters.txt"
    chapters: list[list[str]] = []
    current: list[str] | None = None
    in_book1 = False
    for line in roster_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Book 1"):
            in_book1 = True
        elif line.startswith("## Book 2"):
            break
        elif in_book1 and line.strip().startswith("Chapter 1."):
            current = []
            chapters.append(current)
        elif in_book1 and line.strip().startswith("- "):
            assert current is not None
            current.append(line.strip()[2:])
    import sys
    kit = root / "BookwormAdventuresModding"
    sys.path.insert(0, str(kit))
    from bwakit.game.power_table import MONSTER_TABLE
    result = {}
    for names, stats in zip(chapters, MONSTER_TABLE[0]):
        if len(names) == 1 and len(stats) > 1:
            result[_normal_name(names[0])] = tuple(values[0] for values in stats)
        else:
            result.update(
                (_normal_name(name), values[0])
                for name, values in zip(names, stats)
            )
    return result


def validate_chapter1_state(
    state: "DeluxeState", hp_map: dict[str, int | tuple[int, ...]]
) -> str | None:
    if state.book not in (0, 1):
        return None
    expected = hp_map.get(_roster_name(state.enemy))
    if expected is None:
        return f"Chapter 1 roster has no entry for live enemy {state.enemy!r}"
    if isinstance(expected, tuple):
        head = re.search(r"\(Head (\d+)\)", state.enemy, re.IGNORECASE)
        if "main head" in state.enemy.casefold():
            phase = len(expected) - 1
        else:
            phase = int(head.group(1)) - 1 if head else 0
        if phase >= len(expected):
            return f"Static roster has no phase {phase + 1} for live enemy {state.enemy!r}"
        expected = expected[phase]
    if state.max_hp >= 0 and abs(state.max_hp - expected) > 1e-9:
        return (
            f"Live {state.enemy} max HP is {state.max_hp:g}; "
            f"static Chapter 1 table expects {expected}"
        )
    return None


@dataclass(frozen=True)
class DeluxeState:
    sequence: int
    board: str
    gems: tuple[str, ...]
    tile_powers: tuple[float, ...]
    book: int
    chapter: int
    stage: int
    enemy: str
    hp: float
    max_hp: float
    offense: float
    treasures: frozenset[str]
    overkill_thresholds: tuple[float, ...]
    selectable: tuple[bool, ...] = (True,) * 16
    player_hp: float = -1
    player_max_hp: float = -1


@dataclass(frozen=True)
class Candidate:
    word: str
    path: tuple[int, ...]
    damage: float
    overkill: float
    tier: str | None
    lethal: bool
    predicted_time: float
    gem_count: int


def parse_state(text: str) -> DeluxeState | None:
    ready_sequences = [int(match.group("seq")) for match in READY_SEQ_RE.finditer(text)]
    for sequence in reversed(ready_sequences):
        contexts = [m for m in CONTEXT_RE.finditer(text) if int(m.group("seq")) == sequence]
        enemies = [m for m in ENEMY_RE.finditer(text) if int(m.group("seq")) == sequence]
        healths = [m for m in HEALTH_RE.finditer(text) if int(m.group("seq")) == sequence]
        player_healths = [
            m for m in PLAYER_HEALTH_RE.finditer(text)
            if int(m.group("seq")) == sequence
        ]
        letters = {
            int(m.group("row")): m for m in LETTERS_RE.finditer(text)
            if int(m.group("seq")) == sequence
        }
        gems = {int(m.group("row")): m for m in GEMS_RE.finditer(text) if int(m.group("seq")) == sequence}
        powers = {int(m.group("row")): m for m in POWERS_RE.finditer(text) if int(m.group("seq")) == sequence}
        selectables = {
            int(m.group("row")): m for m in SELECTABLE_RE.finditer(text)
            if int(m.group("seq")) == sequence
        }
        mods = [m for m in MODS_RE.finditer(text) if int(m.group("seq")) == sequence]
        overkills = [m for m in OVERKILL_RE.finditer(text) if int(m.group("seq")) == sequence]
        if contexts and enemies and healths and len(letters) == len(gems) == len(powers) == 4 and mods and overkills:
            break
    else:
        return None
    match = contexts[-1]
    health = healths[-1]
    raw_treasures = mods[-1].group("value")
    treasures = frozenset(
        name.strip().casefold() for name in raw_treasures.split(",")
        if name.strip().casefold() != "none"
    )
    return DeluxeState(
        sequence=sequence,
        board="/".join(letters[row].group("value") for row in range(4)),
        gems=tuple(
            GEM_CODE_NAMES.get(gem, f"bonus-{gem}") for row in range(4)
            for gem in gems[row].group("value").split(",")
        ),
        tile_powers=tuple(
            float(value) for row in range(4)
            for value in powers[row].group("value").split(",")
        ),
        selectable=tuple(
            value == "1" for row in range(4)
            for value in (
                selectables[row].group("value") if row in selectables else "1111"
            )
        ),
        player_hp=(float(player_healths[-1].group("hp")) if player_healths else -1),
        player_max_hp=(
            float(player_healths[-1].group("max_hp")) if player_healths else -1
        ),
        book=int(match.group("book")),
        chapter=int(match.group("chapter")),
        stage=int(match.group("stage")),
        enemy=enemies[-1].group("value").strip(),
        hp=float(health.group("hp")),
        max_hp=float(health.group("max_hp")),
        offense=float(health.group("offense")),
        treasures=treasures,
        overkill_thresholds=tuple(sorted(
            float(value) for value in overkills[-1].group("value").split(",")
        )) if overkills[-1].group("value") != "none" else (),
    )


def ceil_quarter(value: float) -> float:
    return math.ceil((value - 1e-9) * 4.0) / 4.0


def load_metal_words(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    import sys
    kit = Path(__file__).resolve().parents[1] / "BookwormAdventuresModding"
    sys.path.insert(0, str(kit))
    from bwakit.bytecode.luc_disasm import parse

    chunk = parse(str(path))
    return frozenset(
        value.upper() for value in chunk.consts
        if isinstance(value, str) and value.isalpha() and value != "gMetalWordList"
    )


def _path_for_word(state: DeluxeState, word: str) -> tuple[int, ...] | None:
    letters = state.board.replace("/", "")
    needed = Counter(word)
    positions: dict[str, list[int]] = {}
    for index, letter in enumerate(letters):
        if state.selectable[index]:
            positions.setdefault(letter, []).append(index)
    chosen: dict[str, list[int]] = {}
    for letter, count in needed.items():
        available = positions.get(letter, [])
        if len(available) < count:
            return None
        # The same word can use different duplicate tiles. Prefer the live
        # contribution reported by Lua, then a gem, then stable board order.
        ranked = sorted(
            available,
            key=lambda i: (state.tile_powers[i], state.gems[i] != "none", -i),
            reverse=True,
        )
        chosen[letter] = ranked[:count]
    offsets = Counter()
    path = []
    for letter in word:
        path.append(chosen[letter][offsets[letter]])
        offsets[letter] += 1
    return tuple(path)


def damage_for(
    state: DeluxeState, word: str, path: tuple[int, ...], metal_words: frozenset[str]
) -> float:
    base = DAMAGE_BY_LENGTH[len(word)]
    # AUTOMATION_POWERS is calculated inside the game from LETTER_BONUSES and
    # Tile.ApplyBonus. It therefore already includes per-letter treasures such
    # as Wooden Parrot (R) and Bow/Arch of Xyzzy (X/Y/Z), as well as gems. Do
    # not add those treasure bonuses again here.
    tile_bonus = ceil_quarter(sum(state.tile_powers[index] for index in path))
    damage = base + tile_bonus + base * state.offense
    if "hand of hercules" in state.treasures:
        if word in metal_words:
            damage *= 1.5
        damage += 1.0
    elif "heph's hammer" in state.treasures:
        damage += 0.5
    return ceil_quarter(damage)


def overkill_tier(overkill: float, thresholds: tuple[float, ...]) -> str | None:
    if overkill < 0:
        return None
    for threshold, name in reversed(tuple(zip(thresholds, GEM_TIER_NAMES))):
        if overkill + 1e-9 >= threshold:
            return name
    return None


def candidates(
    state: DeluxeState,
    words: list[str],
    metal_words: frozenset[str],
    click_delay: float,
) -> list[Candidate]:
    if state.hp < 0:
        raise RuntimeError("Deluxe did not report a valid enemy HP value")
    unknown = state.treasures - SUPPORTED_DAMAGE_TREASURES
    # Non-damage treasures are harmless. Stop only for names that advertise a
    # direct attack/damage effect and are therefore unsafe to ignore.
    dangerous = {name for name in unknown if "damage" in name or "attack" in name}
    if dangerous:
        raise RuntimeError(f"Unmodelled active damage treasure(s): {sorted(dangerous)}")
    result = []
    for raw_word in words:
        word = raw_word.upper()
        if len(word) not in DAMAGE_BY_LENGTH:
            continue
        path = _path_for_word(state, word)
        if path is None:
            continue
        damage = damage_for(state, word, path, metal_words)
        overkill = damage - state.hp
        gem_count = sum(state.gems[index] in GEM_TIER_NAMES for index in path)
        # Frozen POC timing model: input dominates within an overkill tier;
        # gem activations receive a small measured-cost placeholder that the
        # JSONL telemetry can later replace.
        predicted = 0.35 + len(word) * click_delay + gem_count * 0.10
        result.append(Candidate(
            word, path, damage, overkill, overkill_tier(overkill, state.overkill_thresholds),
            damage + 1e-9 >= state.hp, predicted, gem_count,
        ))
    return result


def choose(cands: list[Candidate], strategy: str) -> tuple[Candidate, dict[str, Candidate]]:
    if not cands:
        raise RuntimeError("The Deluxe optimizer found no playable word")
    lethal = [candidate for candidate in cands if candidate.lethal]
    tier_rank = {name: rank for rank, name in enumerate(GEM_TIER_NAMES)}
    shortest = min(lethal, key=lambda c: (c.predicted_time, len(c.word), -c.damage, c.word)) if lethal else None
    maximum = max(cands, key=lambda c: (c.damage, -c.predicted_time, c.word))
    if strategy == "max-damage":
        selected = maximum
    elif not lethal:
        selected = max(cands, key=lambda c: (c.damage / c.predicted_time, c.damage, -len(c.word), c.word))
    elif strategy == "shortest-lethal":
        selected = shortest
    else:
        selected = max(
            lethal,
            key=lambda c: (
                tier_rank.get(c.tier, -1), -c.predicted_time,
                -len(c.word), c.damage, c.word,
            ),
        )
    alternatives = {"max_damage": maximum}
    if shortest is not None:
        alternatives["shortest_lethal"] = shortest
    return selected, alternatives


def strategy_for_state(
    state: DeluxeState, requested: str, chapter_override: int | None = None
) -> str:
    """Resolve the route strategy from the current chapter's live mechanics."""
    if requested != "chapter-aware":
        return requested
    chapter = state.chapter if state.chapter >= 1 else chapter_override
    if state.book == 1:
        if chapter is not None and 1 <= chapter <= 5:
            return "shortest-lethal"
        if chapter is None and _roster_name(state.enemy) in BOOK1_MIN_KILL_ENEMIES:
            return "shortest-lethal"
    return "overkill-tier" if state.overkill_thresholds else "max-damage"
