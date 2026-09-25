"""Record runner-session identity and the actual experiment build on disk."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def create_session(game_dir: Path) -> str:
    run_id = 'experiment-' + uuid4().hex
    hashes = {}
    for name in ('BookwormAdventures.exe', 'main.pak'):
        digest = hashlib.sha256()
        with (game_dir / name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        hashes[name] = digest.hexdigest()
    manifest = dict(run_id=run_id, started_at=datetime.now(timezone.utc).isoformat(),
                    game_dir=str(game_dir.resolve()), file_hashes=hashes,
                    identity_scope='runner session; not a restored checkpoint',
                    timing_unit='wall seconds', rng_state_captured=False)
    directory = game_dir / 'sessions'
    directory.mkdir(exist_ok=True)
    with (directory / (run_id + '.json')).open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    return run_id
