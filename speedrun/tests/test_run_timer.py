import tempfile
import unittest
from pathlib import Path

from run_timer import (
    mark_current_issue, process_line, record_chapter, report, start_timer,
    update_tas_best,
)


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
        self.assertIn("Book 1 progress: 1:30", text)

    def test_report_compares_chapter_and_cumulative_wr_gaps(self):
        state = self.state()
        record_chapter(state, 1, 1, 100.0)
        record_chapter(state, 1, 2, 160.0)
        state["finished_at"] = 230.0
        state["splits"].append({
            **state["current"], "ended_at": 230.0,
            "elapsed": 70.0,
        })
        state["current"] = None
        text = report(
            state, 230.0,
            {"total_seconds": 120, "chapters": {"1.1": 50, "1.2": 120}},
            {"segments": {"1.1": 55, "1.2": 65}},
        )
        self.assertIn("TAS best 0:55", text)
        self.assertIn("WR 0:50 | chapter +0:10 | cumulative +0:10", text)
        self.assertIn("WR 1:10 | chapter +0:00 | cumulative +0:10", text)
        self.assertIn("Human WR target: 2:00", text)

    def test_completed_book_reports_human_wr_gap(self):
        state = self.state()
        state["splits"] = [
            {"book": 1, "chapter": 10, "elapsed": 100.0},
        ]
        state["finished_at"] = 200.0
        text = report(
            state, 200.0,
            {"book_seconds": {"1": 90.0}, "chapters": {}},
            {"segments": {}},
        )
        self.assertIn(
            "Book 1 total: 1:40 | Human WR 1:30 | gap +0:10", text
        )
        self.assertIn("Human WR books: Book 1 1:30", text)

    def test_tas_best_persists_fastest_completed_segment(self):
        state = self.state()
        state["splits"] = [
            {"book": 1, "chapter": 1, "elapsed": 60.0},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tas-best.json"
            update_tas_best(state, path)
            state["splits"][0]["elapsed"] = 65.0
            best = update_tas_best(state, path)
            self.assertEqual(best["segments"]["1.1"], 60.0)
            state["splits"][0]["elapsed"] = 55.0
            best = update_tas_best(state, path)
            self.assertEqual(best["segments"]["1.1"], 55.0)

    def test_dirty_split_cannot_update_tas_best(self):
        state = self.state()
        record_chapter(state, 1, 1, 100.0)
        self.assertTrue(mark_current_issue(state, "input-retry:TEST"))
        record_chapter(state, 1, 2, 140.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tas-best.json"
            best = update_tas_best(state, path)
        self.assertNotIn("1.1", best["segments"])
        self.assertFalse(state["splits"][0]["clean"])

    def test_unmistakable_pause_is_not_saved_as_best(self):
        state = self.state()
        state["splits"] = [
            {"book": 1, "chapter": 10, "elapsed": 900.0, "clean": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tas-best.json"
            best = update_tas_best(state, path)
        self.assertNotIn("1.10", best["segments"])


if __name__ == "__main__":
    unittest.main()
