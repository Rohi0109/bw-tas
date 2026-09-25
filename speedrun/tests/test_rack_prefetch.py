import unittest
from dataclasses import replace

from deluxe_optimizer import candidates, index_words
from rack_prefetch import RackPrefetch
from test_deluxe_optimizer import state


class RackPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.words = index_words(['TEST', 'TESTS', 'SET', 'TEES', 'AAA', 'ZZZ'])
        self.origin = state(board='TEST/AAAA/AAAA/AAAA', enemy='Sea Serpent')
        self.cache = RackPrefetch()

    def test_prefilter_is_equivalent_to_full_search(self):
        self.assertTrue(self.cache.prepare(self.origin.board, self.words, self.origin))
        filtered = self.cache.take(self.origin.board)
        self.assertEqual(candidates(self.origin, filtered, frozenset(), .01),
                         candidates(self.origin, self.words, frozenset(), .01))
        self.assertIsNone(self.cache.take(self.origin.board))

    def test_changed_board_falls_back_and_discards_cache(self):
        self.cache.prepare(self.origin.board, self.words, self.origin)
        self.assertIsNone(self.cache.take('ZZZZ/ZZZZ/ZZZZ/ZZZZ'))
        self.assertIsNone(self.cache.take(self.origin.board))

    def test_boss_transition_invalidates_prior_prefetch(self):
        for name in ['Polydamas (Boss)', 'Polyphemus', 'Charybdis (Boss)', 'Circe (Boss)']:
            self.cache.prepare(self.origin.board, self.words, self.origin)
            self.assertFalse(self.cache.prepare(self.origin.board, self.words,
                                                 replace(self.origin, enemy=name)))
            self.assertIsNone(self.cache.take(self.origin.board))

    def test_live_hp_gems_treasures_and_selectability_are_not_cached(self):
        self.cache.prepare(self.origin.board, self.words, self.origin)
        live = replace(self.origin, hp=9, enemy='Siren', offense=.25,
                       treasures=frozenset({'bow of zyx'}),
                       tile_powers=(.5,)+(0.,)*15,
                       gems=('ruby',)+('none',)*15,
                       selectable=(True, False)+(True,)*14,
                       zero_damage=(True,)+(False,)*15)
        self.assertEqual(candidates(live, self.cache.take(live.board), frozenset(), .01),
                         candidates(live, self.words, frozenset(), .01))

    def test_empty_prefilter_is_a_valid_cache_hit(self):
        self.cache.prepare('XXXX/XXXX/XXXX/XXXX', self.words, self.origin)
        self.assertEqual(self.cache.take('XXXX/XXXX/XXXX/XXXX'), [])

    def test_invalid_rack_or_unknown_origin_cannot_prefetch(self):
        self.assertFalse(self.cache.prepare('????/AAAA/AAAA/AAAA', self.words, self.origin))
        self.assertFalse(self.cache.prepare(self.origin.board, self.words, None))
