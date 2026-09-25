"""Create an isolated experiment that reseeds before each native SubmitTiles."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'BookwormAdventuresModding'))
from bwakit import popcap_pak_repack
from modkit import transform
from build_lua_hook import bound_method_proto
from prepare_deluxe import extract_entry


def patch_battle(chunk, engine_rng=False):
    if any(kind == 'str' and value.rstrip(b'\0') == b'AutomationResetAttackRng'
           for kind, value in chunk.consts):
        raise ValueError('Attack RNG reset is already installed')
    method = chunk.protos[bound_method_proto(chunk, 'AutomationAttackSubmitted')]
    source_name = 'ResetEngineAttackRng.lua' if engine_rng else 'ResetAttackRng.lua'
    hook = transform.compile_method(str(ROOT/'automation/lua_hook'/source_name),
                                    str(ROOT/'BookwormAdventuresModding/luac'))
    transform.append_bound_method(chunk, 'BattleEngine', 'AutomationResetAttackRng', hook)
    # The submission logger is called at the start of native SubmitTiles.
    # Its final return is after the attack ID and damage telemetry are emitted.
    returns = [pc for pc, word in enumerate(method.code)
               if word & 0x3f == transform.OP_RETURN]
    if len(returns) != 1:
        raise ValueError('Submission logger must have exactly one return')
    transform.inject_self_call(method, 'AutomationResetAttackRng', [],
                               ret_reg=method.maxstack, at_pc=returns[0])


def prepare(source, output, engine_rng=False):
    source, output = source.resolve(), output.resolve()
    if output.exists() or source in output.parents:
        raise ValueError('Destination must be new and outside the source')
    executable = (source/'BookwormAdventures.exe').read_bytes()
    if engine_rng:
        from engine_rng_bridge import bridge
        executable = bridge(executable)
    with tempfile.TemporaryDirectory(prefix='bwa-attack-rng-') as directory:
        temporary = Path(directory)
        battle = temporary/'original.luc'
        extract_entry(source/'main.pak', 'scripts\\BattleEngine.luc', battle)
        chunk = transform.load_chunk(battle)
        patch_battle(chunk, engine_rng)
        target = temporary/'modified/scripts/BattleEngine.luc'
        target.parent.mkdir(parents=True)
        transform.save_chunk(chunk, target)
        pak = temporary/'main.pak'
        _, replaced, _ = popcap_pak_repack.repack(
            str(source/'main.pak'), str(temporary/'modified'), str(pak))
        if replaced != 1:
            raise ValueError('Expected one BattleEngine replacement')
        shutil.copytree(source, output, ignore=shutil.ignore_patterns(
            '*.log', '*.json', '*.jsonl', 'sessions', '.tas-*', '*.lock'))
        shutil.copy2(pak, output/'main.pak')
        if engine_rng:
            (output/'BookwormAdventures.exe').write_bytes(executable)
    manifest = dict(mode='reset-before-each-submit', seed=1,
                    rng_stream='engine' if engine_rng else 'crt',
                    source=str(source),
                    executable_sha256=hashlib.sha256((output/'BookwormAdventures.exe').read_bytes()).hexdigest(),
                    main_pak_sha256=hashlib.sha256((output/'main.pak').read_bytes()).hexdigest(),
                    marker=('AUTOMATION_RNG_RESET=<attack_id>|1|submit|engine|E'
                            if engine_rng else 'AUTOMATION_RNG_RESET=<attack_id>|1|submit|E'),
                    limitations=['Does not restore battle state or control random call ordering after submission.',
                                 ('Lua randomseed targets the shared engine state in this experiment.'
                                  if engine_rng else 'Only the submitting thread is reseeded by this hook.'),
                                 'Three matching live trials are still required.'])
    (output/'rng-experiment.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'runtime/experiments/fixed-seed-game')
    parser.add_argument('--output', type=Path, default=ROOT/'runtime/experiments/attack-seed-game')
    parser.add_argument('--engine-rng', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.engine_rng), indent=2))
