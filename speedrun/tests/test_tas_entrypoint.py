"""Application order and lock cleanup, without sending game input."""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import tas


class TasEntrypointTests(TestCase):
    def test_run_order_and_cleanup_on_every_exit(self):
        for failure in (None, 'prepare', 'follow'):
            with self.subTest(failure=failure), ExitStack() as stack:
                events = []
                settings = SimpleNamespace(log=Path('/tmp/tas-test/lua.log'),
                                           log_level='INFO', log_file=None)
                session = object()
                lock = Mock()
                lock.close.side_effect = lambda: events.append('release')
                stack.enter_context(patch.object(tas, 'read_settings', return_value=settings))
                stack.enter_context(patch.object(tas.game, 'configure_logging',
                                                side_effect=lambda *_: events.append('logging')))
                stack.enter_context(patch.object(tas.game, 'acquire_runner_lock',
                                                side_effect=lambda *_: events.append('claim') or lock))

                def prepare(actual):
                    self.assertIs(actual, settings)
                    events.append('prepare')
                    if failure == 'prepare':
                        raise RuntimeError('startup failed')
                    return session

                def follow(actual):
                    self.assertIs(actual, session)
                    events.append('follow')
                    if failure == 'follow':
                        raise KeyboardInterrupt()

                stack.enter_context(patch.object(tas.game, 'prepare_game', side_effect=prepare))
                stack.enter_context(patch.object(tas.game, 'follow_game_until_finished', side_effect=follow))
                if failure:
                    with self.assertRaises(RuntimeError if failure == 'prepare' else KeyboardInterrupt):
                        tas.main()
                else:
                    tas.main()
                expected = ['logging', 'claim', 'prepare']
                if failure != 'prepare':
                    expected.append('follow')
                self.assertEqual(events, expected + ['release'])
                lock.close.assert_called_once()
