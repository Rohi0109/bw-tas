"""Incremental, bounded progress detection; heartbeat/sequence churn is ignored."""
import re


class TelemetryProgress:
    def __init__(self, path):
        self.path = path
        self.identity = None
        self.offset = 0
        self.pending = b''
        self.values = {}
        try:
            stat = path.stat()
            self.identity = (stat.st_dev, stat.st_ino)
            self.offset = stat.st_size  # Old log contents are not fresh progress.
        except FileNotFoundError:
            pass

    def poll(self):
        try:
            with self.path.open('rb') as stream:
                import os
                stat = os.fstat(stream.fileno())
                identity = (stat.st_dev, stat.st_ino)
                if identity != self.identity or stat.st_size < self.offset:
                    self.offset = 0
                    self.pending = b''
                    self.identity = identity
                stream.seek(self.offset)
                chunk = stream.read(65536)
                self.offset += len(chunk)
        except FileNotFoundError:
            return False
        self.pending += chunk
        # Captured console logs can contain literal backslash-r/backslash-n.
        lines = re.split(rb'\r\n|\n|\\r\\n|\\n', self.pending)
        self.pending = lines.pop()[-65536:]
        changed = False
        for line in lines:
            match = re.search(rb'AUTOMATION_(READY|CONTEXT|ATTACK_HP|DEFEATED)=([^\r\n\\]*)', line)
            if not match:
                continue
            key, value = match.groups()
            if key in (b'CONTEXT', b'ATTACK_HP'):
                # Remove changing sequence/attack IDs; retain actual state.
                fields = value.split(b'|')
                if len(fields) < 3:
                    continue
                value = b'|'.join(fields[1:])
            if self.values.get(key) != value:
                self.values[key] = value
                changed = True
        return changed
