from dataclasses import dataclass
from word.constats import Hand,Arch

@dataclass
class Modifiers:
    parrot: bool = False
    hand: Hand | None = None
    arch: Arch | None = None

def set_modifiers(parrot:bool,hand:Hand,arch:Arch) -> Modifiers:
    # will probably edit this later depending on gm state but for now
    mod = Modifiers(parrot=True,hand=hand.HER,arch = arch.XYZZY)
    return mod