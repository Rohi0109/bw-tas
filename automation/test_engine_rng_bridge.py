import struct
import unittest
from pathlib import Path

from engine_rng_bridge import ADAPTER, BASE, CALL, SEED, bridge


class EngineBridgeTests(unittest.TestCase):
    def test_rejects_unknown_binary(self):
        with self.assertRaises(ValueError):
            bridge(b'wrong build')

    def test_native_patch_targets_engine_seed_and_keeps_stack_cleanup(self):
        path = Path(__file__).resolve().parents[1]/'runtime/experiments/fixed-seed-game/BookwormAdventures.exe'
        if not path.exists():
            self.skipTest('Requires the hash-validated experimental executable')
        source = path.read_bytes()
        output = bridge(source)
        call, adapter = CALL-BASE, ADAPTER-BASE
        self.assertEqual(len(output), len(source))
        self.assertEqual(CALL+5+struct.unpack_from('<i',output,call+1)[0], ADAPTER)
        self.assertEqual(output[adapter:adapter+4], bytes.fromhex('8b 44 24 04'))
        self.assertEqual(ADAPTER+9+struct.unpack_from('<i',output,adapter+5)[0], SEED)
        self.assertEqual(output[call+5:call+8], bytes.fromhex('83 c4 04'))
        allowed = set(range(call,call+5)) | set(range(adapter,adapter+9))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(source,output))))
        with self.assertRaises(ValueError):
            bridge(output)
