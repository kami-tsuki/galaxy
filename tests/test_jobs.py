import threading
import unittest
from unittest import mock

from galaxy import jobs
from tests.helpers import JobsCase, start_patch, wait_idle


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


class CancelTests(JobsCase):
    def test_cancel_flag_round_trip(self):
        self.assertFalse(jobs.cancelled())
        jobs.request_cancel()
        self.assertTrue(jobs.cancelled())
        jobs.clear_cancel()
        self.assertFalse(jobs.cancelled())

    def test_check_cancel_raises_only_when_requested(self):
        jobs.check_cancel()
        jobs.request_cancel()
        with self.assertRaises(jobs.Cancelled):
            jobs.check_cancel()

    def test_cancelled_is_a_runtime_error(self):
        self.assertTrue(issubclass(jobs.Cancelled, RuntimeError))


class IntentStateTests(JobsCase):
    def test_initial_intent_is_down_with_empty_request(self):
        snap = jobs.snapshot()
        self.assertEqual((snap["intent"], snap["request"]), ("down", {}))

    def test_update_stores_intent_and_request(self):
        jobs.update(intent="up", request={"source": "main"})
        snap = jobs.snapshot()
        self.assertEqual((snap["intent"], snap["request"]), ("up", {"source": "main"}))


class SubmitTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.log = start_patch(self, jobs, "log")

    def test_runs_function_in_background_with_args_and_releases_lock(self):
        done = threading.Event()
        jobs.submit(lambda value: done.set() if value == 7 else None, 7)
        self.assertTrue(done.wait(3))
        self.assertTrue(wait_idle())

    def test_lock_is_held_while_running(self):
        started, gate = threading.Event(), threading.Event()
        jobs.submit(lambda: (started.set(), gate.wait(3)))
        self.assertTrue(started.wait(3))
        self.assertTrue(jobs.busy())
        gate.set()
        self.assertTrue(wait_idle())

    def test_raises_busy_while_another_job_runs(self):
        gate = threading.Event()
        jobs.submit(gate.wait)
        try:
            with self.assertRaises(jobs.Busy):
                jobs.submit(lambda: None)
        finally:
            gate.set()
        self.assertTrue(wait_idle())

    def test_busy_is_a_runtime_error(self):
        self.assertTrue(issubclass(jobs.Busy, RuntimeError))

    def test_error_is_reported_into_phase_and_logged_by_default(self):
        jobs.submit(explode)
        self.assertTrue(wait_idle())
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("error", "kaput"))
        message = self.log.call_args.args[0]
        self.assertIn("kaput", message)
        self.assertIn("explode", message)

    def test_error_is_logged_but_not_reported_when_report_is_false(self):
        jobs.submit(explode, report=False)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "idle")
        self.log.assert_called_once()

    def test_cancelled_is_swallowed_without_error_phase_or_log(self):
        def cancel():
            raise jobs.Cancelled("cancelled")

        jobs.submit(cancel)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "idle")
        self.log.assert_not_called()

    def test_lock_is_released_after_failure_so_next_submit_works(self):
        jobs.submit(explode)
        self.assertTrue(wait_idle())
        done = threading.Event()
        jobs.submit(done.set)
        self.assertTrue(done.wait(3))
        self.assertTrue(wait_idle())

    def test_submit_does_not_accept_a_log_parameter(self):
        with self.assertRaises(TypeError):
            jobs.submit(lambda: None, log=print)


class SubmitWaitTests(JobsCase):
    def setUp(self):
        super().setUp()
        start_patch(self, jobs, "log")

    def test_wait_blocks_until_the_running_job_finishes_then_runs(self):
        gate, done = threading.Event(), threading.Event()
        jobs.submit(gate.wait)
        result = {}

        def waiter():
            try:
                jobs.submit(done.set, wait=True)
                result["ok"] = True
            except jobs.Busy:
                result["ok"] = False

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        thread.join(0.05)
        self.assertTrue(thread.is_alive())
        self.assertFalse(done.is_set())
        gate.set()
        thread.join(3)
        self.assertTrue(done.wait(3))
        self.assertTrue(result["ok"])
        self.assertTrue(wait_idle())

    def test_wait_passes_the_lock_wait_timeout(self):
        lock = mock.Mock()
        lock.acquire.return_value = False
        with mock.patch.object(jobs, "_job_lock", lock):
            with self.assertRaises(jobs.Busy):
                jobs.submit(lambda: None, wait=True)
        lock.acquire.assert_called_once_with(timeout=jobs.LOCK_WAIT)

    def test_without_wait_the_lock_is_tried_without_blocking(self):
        lock = mock.Mock()
        lock.acquire.return_value = False
        with mock.patch.object(jobs, "_job_lock", lock):
            with self.assertRaises(jobs.Busy):
                jobs.submit(lambda: None)
        lock.acquire.assert_called_once_with(blocking=False)

    def test_exclusive_no_longer_exists(self):
        self.assertFalse(hasattr(jobs, "exclusive"))


if __name__ == "__main__":
    unittest.main()
