import unittest

from run_timer import process_line, record_chapter, report, start_timer


class RunTimerTests(unittest.TestCase):
    def state(self):
        return {
            "version": 1, "started_at": 100.0, "started_at_iso": "test",
            "current": None, "live_book": 1, "splits": [], "finished_at": None,
        }

    def test_chapter_transition_records_split(self):
        state = self.state()
        self.assertTrue(record_chapter(state, 1, 1, 110.0))
        self.assertTrue(record_chapter(state, 1, 2, 140.0))
        self.assertEqual(state["splits"][0]["elapsed"], 30.0)

    def test_duplicate_context_does_not_split(self):
        state = self.state()
        record_chapter(state, 1, 1, 110.0)
        self.assertFalse(record_chapter(state, 1, 1, 120.0))

    def test_processes_startgame_and_ignores_missing_context_chapter(self):
        state = self.state()
        self.assertTrue(process_line(
            state, "Book:StartGame called for book Book2, chapter 7", 110.0
        ))
        self.assertFalse(process_line(
            state, "AUTOMATION_CONTEXT=4|3|-1|1|E", 120.0
        ))

    def test_enemy_roster_recovers_missing_lua_chapter(self):
        state = self.state()
        self.assertFalse(process_line(
            state, "AUTOMATION_CONTEXT=4|1|-1|1|E", 110.0
        ))
        self.assertTrue(process_line(
            state, "AUTOMATION_ENEMY=4|Angry Mountain Goat|E", 111.0
        ))
        self.assertEqual(state["current"]["chapter"], 2)

    def test_report_has_chapter_book_and_total(self):
        state = self.state()
        record_chapter(state, 1, 1, 110.0)
        record_chapter(state, 1, 2, 140.0)
        text = report(state, 200.0)
        self.assertIn("Total: 1:40", text)
        self.assertIn("Book 1 Chapter 1: 0:30", text)
        self.assertIn("Book 1 total: 1:30", text)


if __name__ == "__main__":
    unittest.main()
