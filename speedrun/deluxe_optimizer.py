"""Deluxe word search, modeled damage and candidate ranking.

Shared values live in combat_models; Lua decoding lives in combat_telemetry.
Legacy imports of those names remain supported below.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from combat_models import Candidate, DeluxeState, WordSpec
# Compatibility exports; new code imports combat_telemetry directly.
from combat_telemetry import (
    CONTEXT_RE,
    ENEMY_RE,
    HEALTH_RE,
    PLAYER_HEALTH_RE,
    PLAYER_STATUS_RE,
    LETTERS_RE,
    GEMS_RE,
    POWERS_RE,
    SELECTABLE_RE,
    ZERO_DAMAGE_RE,
    MODS_RE,
    OVERKILL_RE,
    READY_SEQ_RE,
    RNG_RE,
    GEM_CODE_NAMES,
    parse_state,
)


DAMAGE_BY_LENGTH = {
    # Native DAMAGE_TABLE capture: tier n indexes gDamageByWordLength[n-1].
    0: 0.0, 1: 0.25, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1.0,
    6: 1.5, 7: 2.0, 8: 2.75, 9: 3.5, 10: 4.5, 11: 5.5,
    12: 6.75, 13: 8.0, 14: 9.5, 15: 11.0, 16: 13.0,
}

# Defaults from main.luc's LETTER_BONUSES table. Equipped Bow of Zyx overrides
# X/Y/Z; adjusted_word_length applies that native treasure rule.
LETTER_BONUSES = {
    "B": 0.25, "C": 0.25, "F": 0.25, "H": 0.25,
    "M": 0.25, "P": 0.25,
    "V": 0.5, "W": 0.5, "Y": 0.5,
    "J": 0.75, "K": 0.75,
    "Q": 1.75,
    "X": 1.0, "Z": 1.0,
}

GEM_TIER_NAMES = (
    "amethyst", "sapphire", "emerald", "garnet", "ruby", "crystal", "diamond"
)

ATTACK_ANIMATION_CLASSES = {
    3: "normal", 4: "good", 5: "very-good", 6: "excellent", 7: "awesome",
}

# Median attack-to-zero timings from clean native telemetry. These include
# Lex's visible attack animation and are deliberately conservative: input and
# gem activation costs are still added separately per candidate below.
ATTACK_ANIMATION_SECONDS = {
    "normal": 0.637,
    "good": 0.790,
    "very-good": 0.875,
    "excellent": 0.890,
    "awesome": 0.966,
    "wow-overkill": 1.681,
}


def attack_animation_class(word_length: int) -> str:
    """Return the game's visible attack class for telemetry bucketing."""
    return ATTACK_ANIMATION_CLASSES.get(word_length, "wow-overkill")


def attack_animation_rank(word_length: int) -> int:
    """Order attack classes without pretending their durations are known."""
    return min(max(word_length, 3), 8) - 3

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
    "angryewe": "ewe",
    "angrymountaingoat": "mountaingoat",
    "calydonianboar": "caledonianboar",
    "bronzestymphalian": "stymphalianbirdbronze",
    "steelstymphalian": "stymphalianbirdsteel",
    "thieves91011": "thief91011",
    "thieves121314": "thief121314",
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


def index_words(words: list[str]) -> list[WordSpec]:
    """Precompute immutable letter requirements outside the READY hot path."""
    indexed = []
    for raw_word in words:
        word = raw_word.upper()
        if not 3 <= len(word) <= 16:
            continue
        counts = Counter(word)
        mask = 0
        for letter in counts:
            mask = mask | (1 << (ord(letter) - ord("A")))
        indexed.append(WordSpec(word, mask, tuple(sorted(counts.items()))))
    return indexed


def ceil_quarter(value: float) -> float:
    return math.ceil((value - 1e-9) * 4.0) / 4.0


def floor_quarter(value: float) -> float:
    return math.floor((value + 1e-9) * 4.0) / 4.0


def adjusted_word_length(
    state: DeluxeState, word: str, path: tuple[int, ...]
) -> int:
    """Return the native damage tier after usable intrinsic letter weights."""
    value = 0.0
    for letter, index in zip(word, path):
        if not state.zero_damage[index]:
            bonus = LETTER_BONUSES.get(letter, 0.0)
            # ArtemisBow.luc (displayed as Bow of Zyx) assigns, not adds,
            # 1.5 to each of X/Y/Z in LETTER_BONUSES.
            if "bow of zyx" in state.treasures and letter in "XYZ":
                bonus = 1.5
            value += 1.0 + bonus
    # BattleEngine passes TileEngine:GetWordValue through math.round before
    # indexing gDamageByWordLength. PopCap's positive values round .5 upward.
    return min(max(DAMAGE_BY_LENGTH), math.floor(value + 0.5 + 1e-9))


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
    base = DAMAGE_BY_LENGTH[adjusted_word_length(state, word, path)]
    # Tile.ApplyBonus reports bonuses layered on top of the native weighted
    # length tier, such as gems and treasure effects.
    tile_contributions = []
    for index in path:
        contribution = state.tile_powers[index]
        # ModifyValue suppression is already applied before tier lookup.
        tile_contributions.append(contribution)
    tile_bonus = ceil_quarter(sum(tile_contributions))
    damage = max(0.0, base + tile_bonus + base * state.offense)
    if "hand of hercules" in state.treasures:
        if word in metal_words:
            damage *= 1.5
        damage += 1.0
    elif "heph's hammer" in state.treasures:
        # Retain the existing Hammer rule; the current native validation
        # capture covers plain-rack Book 1 attacks, not Hammer resolution.
        damage = floor_quarter(damage) + 0.5
    # Native nonlethal HP edges truncate the final amount to quarter hearts.
    return floor_quarter(damage)


def overkill_tier(overkill: float, thresholds: tuple[float, ...]) -> str | None:
    if overkill < 0:
        return None
    for threshold, name in reversed(tuple(zip(thresholds, GEM_TIER_NAMES))):
        if overkill + 1e-9 >= threshold:
            return name
    return None


def candidates(
    state: DeluxeState,
    words: list[str] | list[WordSpec],
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
    available = Counter(
        letter for index, letter in enumerate(state.board.replace("/", ""))
        if state.selectable[index]
    )
    available_mask = 0
    for letter in available:
        available_mask = available_mask | (1 << (ord(letter) - ord("A")))
    result = []
    for raw_word in words:
        if isinstance(raw_word, WordSpec):
            if raw_word.letter_mask & ~available_mask:
                continue
            if any(
                available.get(letter, 0) < count
                for letter, count in raw_word.requirements
            ):
                continue
            word = raw_word.word
        else:
            word = raw_word.upper()
        if not 3 <= len(word) <= 16:
            continue
        path = _path_for_word(state, word)
        if path is None:
            continue
        damage = damage_for(state, word, path, metal_words)
        overkill = damage - state.hp
        gem_types = tuple(
            state.gems[index] for index in path
            if state.gems[index] in GEM_TIER_NAMES
        )
        gem_count = len(gem_types)
        # Native timing model: Lex's animation class dominates long finishers.
        # Keep input and gem activations explicit so equal animation classes
        # still prefer the shorter, less decorated lethal path.
        animation_class = attack_animation_class(len(word))
        predicted = (
            ATTACK_ANIMATION_SECONDS[animation_class]
            + len(word) * click_delay + gem_count * 0.10
        )
        result.append(Candidate(
            word, path, damage, overkill, overkill_tier(overkill, state.overkill_thresholds),
            damage + 1e-9 >= state.hp, predicted, gem_count, gem_types,
            animation_class,
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
    elif strategy == "speed-sapphire" and not lethal:
        sapphire = [
            candidate for candidate in cands
            if "sapphire" in candidate.gem_types
        ]
        pool = sapphire or cands
        selected = max(
            pool,
            key=lambda c: (
                c.damage / c.predicted_time,
                c.damage,
                -attack_animation_rank(len(c.word)),
                -c.predicted_time,
                c.word,
            ),
        )
    elif not lethal:
        selected = max(cands, key=lambda c: (c.damage / c.predicted_time, c.damage, -len(c.word), c.word))
    elif strategy == "speed-sapphire":
        selected = min(
            lethal,
            key=lambda c: (
                c.tier != "sapphire",
                "sapphire" in c.gem_types,
                attack_animation_rank(len(c.word)),
                c.predicted_time,
                c.overkill,
                c.word,
            ),
        )
    elif strategy == "minimum-overkill":
        selected = min(
            lethal,
            key=lambda c: (c.overkill, c.predicted_time, len(c.word), c.word),
        )
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
        # These Chapter 10 Gorgon checkpoints are immediately menu-reset after
        # DEFEATED, so overkill reward tiers have no route value. Minimize the
        # measured time to the lethal edge instead.
        if _roster_name(state.enemy) in {"pemphredo", "enyo"}:
            return "shortest-lethal"
        if chapter is not None and 1 <= chapter <= 5:
            return "shortest-lethal"
        if chapter is None and _roster_name(state.enemy) in BOOK1_MIN_KILL_ENEMIES:
            return "shortest-lethal"
    return "overkill-tier" if state.overkill_thresholds else "max-damage"
