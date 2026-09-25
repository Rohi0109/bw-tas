"""Diagnostic reset cycles. Observations never authorize game input."""

import json
import logging
import re
import time
import uuid
from pathlib import Path


class MenuTrace(logging.Handler):
    def __init__(self, path, run_id=None, clock=time.monotonic):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.clock = clock
        self.cycle = None
        self.started = None
        self.context = {}
        self.attack_requested = False

    def begin(self):
        if self.cycle:
            self.event('superseded', status='incomplete')
        self.cycle = uuid.uuid4().hex
        self.started = self.clock()
        self.attack_requested = False
        self.event('reset_requested', context=dict(self.context))

    def event(self, stage, **fields):
        if not self.cycle:
            return
        now = self.clock()
        record = dict(run_id=self.run_id, cycle_id=self.cycle,
                      monotonic=now, elapsed=now-self.started, stage=stage, **fields)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True)+'\n')

    def emit(self, record):
        message = record.getMessage()
        if message.startswith('State '):
            self.context['state'] = message
            self.event('live_state_reported', message=message)
        if 'menu reset ' in message or 'immediate reset through the main menu' in message:
            self.context['reason'] = message
        if message.startswith('Retrying Adventure'):
            self.event('adventure_retry_requested', message=message)
        if message.startswith('Chapter-map action confirmed:'):
            self.event('chapter_action_observed', message=message)
        if message.startswith('Fresh READY sequence '):
            self.event('ready_rearmed', message=message)
        if re.match(r'Attack \d+:', message):
            self.attack_requested = True
            self.event('attack_requested', message=message)
        if self.attack_requested and message.startswith('Attack timing ') and (
            'submitted_ack;' in message or 'submitted during presentation skip;' in message
        ):
            self.event('attack_acknowledged', status='complete', message=message)
            elapsed = self.clock()-self.started if self.started is not None else 0
            cycle = self.cycle
            self.cycle = None
            if cycle:
                logging.getLogger('bookworm.tas').info(
                    'Menu reset cycle %s completed through attack acknowledgement in %.3fs', cycle, elapsed)

    def close(self):
        if self.cycle:
            self.event('trace_closed', status='incomplete')
            self.cycle = None
        super().close()
