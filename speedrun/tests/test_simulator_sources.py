import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from simulator_sources import inventory, main, popcap_pak


def pak_bytes(members):
    table = struct.pack('<II', popcap_pak.MAGIC, 0)
    for name, payload in members:
        name = name.encode('ascii')
        table += b'\0' + bytes([len(name)]) + name + struct.pack('<IQ', len(payload), 0)
    return popcap_pak.dexor(table + b'\x80' + b''.join(p for _, p in members))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'game'
        self.source.mkdir()
        (self.source / 'BookwormAdventures.exe').write_bytes(b'MZfixture')
        self.battle = b'\x1bLuaV\0AutomationResetAttackRng\0'
        self.write_pak(self.battle)

    def write_pak(self, battle):
        (self.source / 'main.pak').write_bytes(pak_bytes([
            ('scripts\\BattleEngine.luc', battle),
            ('scripts\\effects\\Poison.luc', b'\x1bLuaVeffect'),
            ('images\\ignored.png', b'image')]))

    def manifest(self, **fields):
        (self.source / 'rng-experiment.json').write_text(json.dumps(fields))

    def codes(self, report):
        return [issue['code'] for issue in report['issues']]

    def test_hashes_and_reproducibility(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        report = inventory(self.source)
        self.assertEqual(report, inventory(self.source))
        self.assertEqual(len(report['members']), 2)
        self.assertEqual(report['members'][0]['sha256'], hashlib.sha256(self.battle).hexdigest())
        for name, info in report['files'].items():
            self.assertEqual(info['sha256'], hashlib.sha256(before[name]).hexdigest())
        self.assertTrue(report['hooks']['AutomationResetAttackRng'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})

    def test_both_manifest_formats_ignore_original_exe_hash(self):
        files = inventory(self.source)['files']
        for field in ('executable_sha256', 'experiment_executable_sha256'):
            self.manifest(**{field: files['BookwormAdventures.exe']['sha256'],
                             'main_pak_sha256': files['main.pak']['sha256'],
                             'source_executable_sha256': '0' * 64})
            self.assertEqual(inventory(self.source)['issues'], [])

    def test_stale_manifest_and_absent_hook(self):
        self.manifest(executable_sha256='0' * 64, main_pak_sha256='1' * 64)
        self.write_pak(b'\x1bLuaVno hook')
        codes = self.codes(inventory(self.source))
        self.assertEqual(codes.count('manifest_hash_mismatch'), 2)
        self.assertIn('reset_hook_absent', codes)

    def test_invalid_and_incomplete_manifests(self):
        path = self.source / 'rng-experiment.json'
        for value in (b'{', b'[]', b'\xff'):
            path.write_bytes(value)
            self.assertIn('manifest_invalid', self.codes(inventory(self.source)))
        self.manifest(executable_sha256=None)
        codes = self.codes(inventory(self.source))
        self.assertIn('manifest_hash_invalid', codes)
        self.assertIn('manifest_pak_hash_missing', codes)

    def test_malformed_archives_rejected(self):
        path = self.source / 'main.pak'
        good = path.read_bytes()
        duplicate = pak_bytes([('scripts\\A.luc', b'a'), ('SCRIPTS/A.luc', b'b')])
        for data in (b'', good[:-1], good + b'x', duplicate,
                     popcap_pak.dexor(struct.pack('<II', popcap_pak.MAGIC, 0) + b'\x01')):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                inventory(self.source)

    def test_cli_exclusive_reproducible_output(self):
        first, second = self.root / 'first.json', self.root / 'second.json'
        for output in (first, second):
            self.assertEqual(main(['--source', str(self.source), '--output', str(output)]), 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        before = first.read_bytes()
        with self.assertRaises(FileExistsError):
            main(['--source', str(self.source), '--output', str(first)])
        self.assertEqual(first.read_bytes(), before)

    def test_output_inside_source_and_symlink_alias_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        for output in (self.source / 'report.json', alias / 'report.json'):
            with self.assertRaises(SystemExit):
                main(['--source', str(self.source), '--output', str(output)])
            self.assertFalse(output.exists())

    def test_missing_battle_and_empty_script_inventory(self):
        (self.source / 'main.pak').write_bytes(pak_bytes([]))
        self.assertEqual(self.codes(inventory(self.source)),
                         ['script_bytecodes_absent', 'reset_hook_absent'])


if __name__ == '__main__':
    unittest.main()
