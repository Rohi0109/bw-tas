"""Read-only simulator source inventory; no extraction or game execution.

Run: python -m speedrun.simulator_sources --source runtime/deluxe-modded
     --output /tmp/new-source-inventory.json
Hashes cover on-disk EXE/PAK bytes and decoded PAK member bytes. All script
bytecodes are included to avoid silently excluding enemy/effect dependencies.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'BookwormAdventuresModding'))
from bwakit import popcap_pak

EXECUTABLE = 'BookwormAdventures.exe'
HOOK = b'AutomationResetAttackRng'


def identity(data):
    return dict(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def read_pak(path):
    """Use the shared decoder, rejecting layouts its permissive parser accepts."""
    raw = path.read_bytes()
    data = popcap_pak.dexor(raw)
    if len(data) < 9 or struct.unpack_from('<I', data)[0] != popcap_pak.MAGIC:
        raise ValueError('Invalid PAK header')
    if struct.unpack_from('<I', data, 4)[0] != 0:
        raise ValueError('Unsupported PAK version')
    offset, payload_size, names = 8, 0, set()
    while True:
        if offset >= len(data):
            raise ValueError('Missing PAK table terminator')
        flag = data[offset]
        offset += 1
        if flag == 0x80:
            break
        if flag != 0 or offset >= len(data):
            raise ValueError('Invalid PAK table entry')
        length = data[offset]
        offset += 1
        if not length or offset + length + 12 > len(data):
            raise ValueError('Truncated PAK table entry')
        name = data[offset:offset + length].decode('latin-1').replace('\\', '/').lower()
        if name in names:
            raise ValueError(f'Duplicate PAK member: {name}')
        names.add(name)
        offset += length
        payload_size += struct.unpack_from('<I', data, offset)[0]
        offset += 12
    if offset + payload_size != len(data):
        raise ValueError('PAK payload size does not match table')
    decoded, entries = popcap_pak.parse(str(path))
    if decoded != data:
        raise ValueError('PAK changed during inventory')
    return raw, decoded, entries


def inventory(source):
    """Return deterministic metadata for one installation without writing to it."""
    source = Path(source).resolve(strict=True)
    executable = (source / EXECUTABLE).read_bytes()
    raw, data, entries = read_pak(source / 'main.pak')
    members = []
    battle = None
    for entry in entries:
        name = entry['name'].replace('\\', '/')
        if name.lower().startswith('scripts/') and name.lower().endswith('.luc'):
            payload = data[entry['data_off']:entry['data_off'] + entry['size']]
            members.append(dict(name=name, **identity(payload)))
            if name.lower() == 'scripts/battleengine.luc':
                battle = payload
    issues = []
    if not members:
        issues.append(dict(code='script_bytecodes_absent'))
    hook_present = battle is not None and HOOK in battle
    if not hook_present:
        issues.append(dict(code='reset_hook_absent', member='scripts/BattleEngine.luc'))
    files = {EXECUTABLE: identity(executable), 'main.pak': identity(raw)}
    manifest_path = source / 'rng-experiment.json'
    manifest = dict(status='absent')
    if manifest_path.exists():
        manifest_bytes = manifest_path.read_bytes()
        manifest = dict(status='present', **identity(manifest_bytes), checks=[])
        try:
            value = json.loads(manifest_bytes)
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object')
            # source_executable_sha256 describes the pre-patch build, not this EXE.
            fields = {'experiment_executable_sha256': EXECUTABLE,
                      'executable_sha256': EXECUTABLE, 'main_pak_sha256': 'main.pak'}
            if not any(field in value for field in tuple(fields)[:2]):
                issues.append(dict(code='manifest_executable_hash_missing'))
            if 'main_pak_sha256' not in value:
                issues.append(dict(code='manifest_pak_hash_missing'))
            for field, filename in fields.items():
                if field not in value:
                    continue
                expected = value[field]
                valid = (isinstance(expected, str) and len(expected) == 64
                         and all(c in '0123456789abcdefABCDEF' for c in expected))
                actual = files[filename]['sha256']
                matches = valid and expected.lower() == actual
                manifest['checks'].append(dict(field=field, expected=expected,
                                                actual=actual, matches=matches))
                if not matches:
                    issues.append(dict(code='manifest_hash_mismatch' if valid
                                       else 'manifest_hash_invalid', field=field))
        except (ValueError, UnicodeError):
            manifest['status'] = 'invalid'
            issues.append(dict(code='manifest_invalid'))
    return dict(schema_version=1, source=str(source), hash_algorithm='sha256',
                files=files, members=sorted(members, key=lambda item: item['name']),
                experiment_manifest=manifest,
                hooks=dict(AutomationResetAttackRng=hook_present), issues=issues,
                limitations=[
                    'Hook detection is byte-string presence, not execution or call-site validation.',
                    'Hashes identify sources; they do not establish simulator fidelity.',
                    'Reads are not an atomic snapshot; inventory quiescent installations.',
                ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    runtime = (ROOT / 'runtime').resolve()
    if output == source or source in output.parents or runtime == output or runtime in output.parents:
        parser.error('Output must be outside runtime installations and the source directory')
    report = inventory(source)
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
    # Exclusive creation also refuses existing files and dangling symlinks.
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(serialized)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
