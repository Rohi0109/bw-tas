"""Stage isolated pre-submit scalar telemetry; never modify the normal install."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from prepare_attack_rng_experiment import ROOT, transform, popcap_pak_repack
from prepare_deluxe import extract_entry
from build_lua_hook import bound_method_proto
from capture_native_rng import EXE_HASH


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or source in output.parents:
        raise ValueError('Capture installation must be new and outside source')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(source/'BookwormAdventures.exe') != EXE_HASH:
        raise ValueError('Unsupported native capture build')
    with tempfile.TemporaryDirectory(prefix='bwa-sim-capture-') as directory:
        temporary = Path(directory)
        original = temporary/'BattleEngine.luc'
        extract_entry(source/'main.pak', 'scripts\\BattleEngine.luc', original)
        chunk = transform.load_chunk(original)
        method = chunk.protos[bound_method_proto(chunk, 'AutomationAttackSubmitted')]
        hook = transform.compile_method(str(ROOT/'automation/lua_hook/DumpSimulationState.lua'),
                                        str(ROOT/'BookwormAdventuresModding/luac'))
        transform.append_bound_method(chunk, 'BattleEngine', 'AutomationSimulationState', hook)
        returns = [i for i,w in enumerate(method.code) if w & 63 == transform.OP_RETURN]
        if len(returns) != 1:
            raise ValueError('Unexpected submission hook control flow')
        transform.inject_self_call(method, 'AutomationSimulationState', [],
                                   ret_reg=method.maxstack, at_pc=returns[0])
        modified = temporary/'modified/scripts/BattleEngine.luc'
        modified.parent.mkdir(parents=True)
        transform.save_chunk(chunk, modified)
        pak = temporary/'main.pak'
        _, replaced, _ = popcap_pak_repack.repack(str(source/'main.pak'), str(temporary/'modified'), str(pak))
        if replaced != 1:
            raise ValueError('Expected exactly one script replacement')
        shutil.copytree(source, output, ignore=shutil.ignore_patterns('*.log','*.jsonl','.tas-*','*.lock'))
        shutil.copy2(pak, output/'main.pak')
    manifest = dict(executable_sha256=digest(output/'BookwormAdventures.exe'),
                    source_pak_sha256=digest(source/'main.pak'),
                    capture_pak_sha256=digest(output/'main.pak'),
                    hook_sha256=digest(ROOT/'automation/lua_hook/DumpSimulationState.lua'),
                    limitations=['Pre-submit scalars only, no complete game checkpoint or restore.',
                                 'Effect queues, QRand state and animation state remain unsupported.',
                                 'RNG debugger trace and Lua log require causal alignment.'])
    (output/'sim-capture-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'runtime/deluxe-modded')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source,args.output),indent=2))
