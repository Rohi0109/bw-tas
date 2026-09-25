import unittest

from attack_lifecycle import AttackLifecycle


class AttackLifecycleTests(unittest.TestCase):
    def test_authorized_selection_still_needs_acknowledgement(self):
        attack = AttackLifecycle(native_authorized=True)
        attack.begin_submission('TEST/AAAA/AAAA/AAAA', 'TEST', (0, 1, 2, 3))
        attack.retry_at = 10
        self.assertEqual(attack.attempts, 1)
        self.assertFalse(attack.acknowledged)
        self.assertFalse(attack.retry_is_due(9, input_blocked=False))
        self.assertFalse(attack.retry_is_due(10, input_blocked=True))
        self.assertTrue(attack.retry_is_due(10, input_blocked=False))
        attack.acknowledge()
        self.assertFalse(attack.retry_is_due(100, input_blocked=False))
        self.assertEqual(attack.word, 'TEST')  # retained for outcome recording

    def test_overlay_cancels_pending_selection_not_historical_policy(self):
        attack = AttackLifecycle(native_authorized=True, strategy='shortest-lethal')
        attack.begin_submission('TEST/AAAA/AAAA/AAAA', 'TEST', (0, 1, 2, 3))
        attack.started_at, attack.attack_sent_at = 1, 2
        attack.retry_at = float('inf')  # overlay owner disables retries first
        attack.discard_interrupted_selection()
        self.assertIsNone(attack.word)
        self.assertIsNone(attack.path)
        self.assertIsNone(attack.started_at)
        self.assertIsNone(attack.attack_sent_at)
        self.assertEqual(attack.attempts, 0)
        self.assertFalse(attack.retry_is_due(100, input_blocked=False))
        self.assertEqual(attack.strategy, 'shortest-lethal')
        self.assertTrue(attack.native_authorized)  # preserves the pre-refactor edge

    def test_sessions_do_not_share_candidate_frontiers(self):
        first, second = AttackLifecycle(), AttackLifecycle()
        first.frontier.append('test sentinel')
        self.assertEqual(second.frontier, [])
