import threading
import unittest
from unittest import mock

from galaxy import jobs
from tests.helpers import JobsCase, wait_idle


def explode():
    raise RuntimeError("kaput")


class StateTests(JobsCase):
    def test_set_phase_updates_phase_and_error(self):
        jobs.set_phase("error", "bad")
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("error", "bad"))

    def test_set_phase_clears_error_by_default(self):
        jobs.set_phase("error", "bad")
        jobs.set_phase("idle")
        self.assertEqual(jobs.snapshot()["error"], "")

    def test_snapshot_is_a_copy(self):
        jobs.snapshot()["phase"] = "hacked"
        self.assertEqual(jobs.snapshot()["phase"], "idle")

    def test_update_keeps_unrelated_keys(self):
        jobs.update(source="main")
        jobs.update(warning="w")
        snap = jobs.snapshot()
        self.assertEqual((snap["source"], snap["warning"]), ("main", "w"))


class CacheTests(JobsCase):
    def test_cached_reuses_value_within_ttl(self):
        producer = mock.Mock(side_effect=[1, 2])
        with mock.patch.object(jobs.time, "time", side_effect=[100, 101]):
            first = jobs.cached("k", 5, producer)
            second = jobs.cached("k", 5, producer)
        self.assertEqual((first, second), (1, 1))
        producer.assert_called_once()

    def test_cached_recomputes_after_ttl(self):
        producer = mock.Mock(side_effect=[1, 2])
        with mock.patch.object(jobs.time, "time", side_effect=[100, 106, 106]):
            first = jobs.cached("k", 5, producer)
            second = jobs.cached("k", 5, producer)
        self.assertEqual((first, second), (1, 2))

    def test_cached_keys_are_independent(self):
        self.assertEqual(jobs.cached("a", 60, lambda: "x"), "x")
        self.assertEqual(jobs.cached("b", 60, lambda: "y"), "y")

    def test_cached_stores_none_results_for_ttl(self):
        producer = mock.Mock(return_value=None)
        jobs.cached("k", 60, producer)
        jobs.cached("k", 60, producer)
        producer.assert_called_once()

    def test_invalidate_forces_recompute(self):
        producer = mock.Mock(side_effect=[1, 2])
        jobs.cached("k", 60, producer)
        jobs.invalidate("k")
        self.assertEqual(jobs.cached("k", 60, producer), 2)

    def test_invalidate_unknown_key_is_harmless(self):
        jobs.invalidate("never-set")


class ExclusiveTests(JobsCase):
    def test_returns_function_result_and_releases_lock(self):
        self.assertEqual(jobs.exclusive(lambda a, b: a + b, 1, 2), 3)
        self.assertFalse(jobs.busy())

    def test_busy_while_running(self):
        seen = {}

        def inner():
            seen["busy"] = jobs.busy()
            with self.assertRaises(jobs.Busy):
                jobs.exclusive(lambda: None)

        jobs.exclusive(inner)
        self.assertTrue(seen["busy"])

    def test_lock_is_released_when_function_raises(self):
        with self.assertRaises(RuntimeError):
            jobs.exclusive(explode)
        self.assertFalse(jobs.busy())

    def test_busy_is_a_runtime_error(self):
        self.assertTrue(issubclass(jobs.Busy, RuntimeError))


class SubmitTests(JobsCase):
    def test_runs_function_in_background_with_args_and_releases_lock(self):
        done = threading.Event()
        jobs.submit(lambda value: done.set() if value == 7 else None, 7)
        self.assertTrue(done.wait(3))
        self.assertTrue(wait_idle())

    def test_raises_busy_while_another_job_runs(self):
        gate = threading.Event()
        jobs.submit(gate.wait)
        try:
            with self.assertRaises(jobs.Busy):
                jobs.submit(lambda: None)
            with self.assertRaises(jobs.Busy):
                jobs.exclusive(lambda: None)
        finally:
            gate.set()
        self.assertTrue(wait_idle())

    def test_error_is_reported_into_phase_by_default(self):
        log = mock.Mock()
        jobs.submit(explode, log=log)
        self.assertTrue(wait_idle())
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("error", "kaput"))
        self.assertIn("kaput", log.call_args.args[0])
        self.assertIn("explode", log.call_args.args[0])

    def test_error_is_not_reported_when_report_is_false(self):
        log = mock.Mock()
        jobs.submit(explode, report=False, log=log)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "idle")
        log.assert_called_once()

    def test_lock_is_released_after_failure_so_next_submit_works(self):
        jobs.submit(explode, log=mock.Mock())
        self.assertTrue(wait_idle())
        done = threading.Event()
        jobs.submit(done.set)
        self.assertTrue(done.wait(3))
        self.assertTrue(wait_idle())


if __name__ == "__main__":
    unittest.main()
