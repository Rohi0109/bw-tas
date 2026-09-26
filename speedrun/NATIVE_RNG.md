# Native engine RNG

`native_rng.NativeRng` implements the engine stream used by `sexy.NextRand`
and the native letter picker. It is distinct from CRT/Lua `math.random`.

Recovered from the installed executable SHA-256
`7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67`:

- Initializer `0x5ab410`, seed routine `0x5ab440`, draw routine `0x5ab4b0`.
- State: 624 unsigned words at `0x767030`, cursor at `0x7679f0`.
- Standard MT19937 initialization/twist/tempering, but outputs are masked to
  31 bits, not shifted. Seed zero substitutes `0x1105`; input seeds wrap to 32 bits.
- Snapshots copy the entire state and cursor. This does not snapshot other game
  state, the CRT stream, or cosmetic consumers of this stream.

## Independent verification

The optional tests execute the original x86 routine bytes with Unicorn in
isolated mapped memory. No PE entry point, Wine, window, or game process runs.
Routine byte hashes and twist constants are checked before execution.

```sh
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -p 'test_native_rng.py' -v
```

With Unicorn installed and the local executable present, all seven tests run.
Without either, the three executable-oracle tests explicitly skip. On
2026-09-26 all seven passed using Unicorn 2.1.4, including 25,000 seed-series
draw comparisons, arbitrary-state comparisons, complete state equality at
twist boundaries, initializer behavior, and bidirectional snapshot/restore.

This establishes parity for the RNG primitive. It does not establish initial
gameplay state or which draws animation, enemies, rewards, and refills consume.
