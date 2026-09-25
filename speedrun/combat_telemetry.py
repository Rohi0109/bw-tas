"""Decode sequence-tagged Lua snapshots without solving or sending input."""

import re

from combat_models import DeluxeState


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
PLAYER_STATUS_RE = re.compile(
    r"AUTOMATION_PLAYER_STATUS=(?P<seq>\d+)\|(?P<stunned>[01])\|"
    r"(?P<health_potion>[01])(?:\|(?P<damage_over_time>[01]))?"
    r"(?:\|(?P<petrified>[01]))?(?:\|(?P<attack_potion>[01]))?"
    r"(?:\|(?P<frozen>[01]))?(?:\|(?P<powered_up>[01]))?"
    r"(?:\|(?P<damage_multiplier>-?\d+(?:\.\d+)?))?\|E"
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
ZERO_DAMAGE_RE = re.compile(
    r"AUTOMATION_ZERO_DAMAGE=(?P<seq>\d+)\|(?P<row>[0-3])\|"
    r"(?P<value>[01]{4})\|E"
)
MODS_RE = re.compile(r"AUTOMATION_MODS=(?P<seq>\d+)\|(?P<value>[^|]+)\|E")
OVERKILL_RE = re.compile(
    r"AUTOMATION_OVERKILL=(?P<seq>\d+)\|"
    r"(?P<value>none|-?\d+(?:\.\d+)?(?:,-?\d+(?:\.\d+)?)*)\|E"
)
READY_SEQ_RE = re.compile(r"AUTOMATION_READY_SEQ=(?P<seq>\d+)\|E")
RNG_RE = re.compile(
    r"AUTOMATION_RNG=(?P<seq>\d+)\|(?P<calls>-?\d+)\|E"
)
GEM_CODE_NAMES = {
    "n": "none", "a": "amethyst", "s": "sapphire", "e": "emerald",
    "g": "garnet", "r": "ruby", "c": "crystal", "d": "diamond",
    "m": "metal",
}

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
        player_statuses = [
            m for m in PLAYER_STATUS_RE.finditer(text)
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
        zero_damage = {
            int(m.group("row")): m for m in ZERO_DAMAGE_RE.finditer(text)
            if int(m.group("seq")) == sequence
        }
        mods = [m for m in MODS_RE.finditer(text) if int(m.group("seq")) == sequence]
        overkills = [m for m in OVERKILL_RE.finditer(text) if int(m.group("seq")) == sequence]
        rng = [m for m in RNG_RE.finditer(text) if int(m.group("seq")) == sequence]
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
        zero_damage=tuple(
            value == "1" for row in range(4)
            for value in (
                zero_damage[row].group("value") if row in zero_damage else "0000"
            )
        ),
        rng_calls=int(rng[-1].group("calls")) if rng else -1,
        player_hp=(float(player_healths[-1].group("hp")) if player_healths else -1),
        player_max_hp=(
            float(player_healths[-1].group("max_hp")) if player_healths else -1
        ),
        player_stunned=(
            player_statuses[-1].group("stunned") == "1"
            if player_statuses else False
        ),
        player_petrified=(
            player_statuses[-1].group("petrified") == "1"
            if player_statuses and player_statuses[-1].group("petrified")
            else False
        ),
        player_frozen=(
            player_statuses[-1].group("frozen") == "1"
            if player_statuses and player_statuses[-1].group("frozen")
            else False
        ),
        health_potion_available=(
            player_statuses[-1].group("health_potion") == "1"
            if player_statuses else False
        ),
        attack_potion_available=(
            player_statuses[-1].group("attack_potion") == "1"
            if player_statuses and player_statuses[-1].group("attack_potion")
            else False
        ),
        player_powered_up=(
            player_statuses[-1].group("powered_up") == "1"
            if player_statuses and player_statuses[-1].group("powered_up")
            else False
        ),
        player_damage_multiplier=(
            float(player_statuses[-1].group("damage_multiplier"))
            if player_statuses and
            player_statuses[-1].group("damage_multiplier") else 1.0
        ),
        player_has_damage_over_time=(
            player_statuses[-1].group("damage_over_time") == "1"
            if player_statuses and player_statuses[-1].group("damage_over_time")
            else False
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

