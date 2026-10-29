import subprocess
import unittest
from unittest import mock

from galaxy import jobs, pc, player, session, watchdog
from tests.helpers import JobsCase, TempDirCase, make_cfg, start_patch

ROUTES = (
    "Iface\tDestination\tGateway\tFlags\n"
    "eth0\t0000A8C0\t00000000\t0001\n"
    "wlan0\t00000000\t0100A8C0\t0003\n"
)
DEV = (
    "Inter-|   Receive\n"
    " face |bytes    packets\n"
    "    lo: 1000 10 0 0\n"
    "  eth0: 123456 99 0 0\n"
    " wlan0: 777 5 0 0\n"
)
REQUEST = {"source": "second", "audio": "tv", "app": "Steam Big Picture"}
START = 1000.0


class FakeClock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


class ProcFileTests(TempDirCase):
    def test_default_interface_is_the_one_with_the_zero_destination(self):
        self.assertEqual(watchdog.default_interface(self.write("route", ROUTES)), "wlan0")

    def test_default_interface_is_empty_without_a_default_route(self):
        path = self.write("route", "Iface\tDestination\tGateway\neth0\t0000A8C0\t00000000\n")
        self.assertEqual(watchdog.default_interface(path), "")

    def test_default_interface_ignores_short_lines_and_header(self):
        self.assertEqual(watchdog.default_interface(self.write("route", "Iface\nwlan0\n")), "")

    def test_default_interface_is_empty_when_the_file_is_missing(self):
        self.assertEqual(watchdog.default_interface(self.dir / "nope"), "")

    def test_rx_bytes_reads_the_named_interface(self):
        path = self.write("dev", DEV)
        self.assertEqual(watchdog.rx_bytes("eth0", path), 123456)
        self.assertEqual(watchdog.rx_bytes("wlan0", path), 777)

    def test_rx_bytes_does_not_match_a_longer_interface_name(self):
        self.assertIsNone(watchdog.rx_bytes("eth", self.write("dev", DEV)))

    def test_rx_bytes_is_none_for_unknown_interface_or_missing_file(self):
        self.assertIsNone(watchdog.rx_bytes("eth9", self.write("dev", DEV)))
        self.assertIsNone(watchdog.rx_bytes("eth0", self.dir / "nope"))

    def test_rx_bytes_is_none_for_garbage_counters(self):
        self.assertIsNone(watchdog.rx_bytes("eth0", self.write("dev", "eth0: lots\n")))
        self.assertIsNone(watchdog.rx_bytes("eth0", self.write("empty", "eth0:\n")))


class PowerFlagsTests(unittest.TestCase):
    def flags(self, **kwargs):
        with mock.patch.object(watchdog.subprocess, "run", **kwargs):
            return watchdog.power_flags()

    def test_parses_the_hex_value(self):
        self.assertEqual(self.flags(return_value=mock.Mock(stdout="throttled=0x50005\n")), 0x50005)

    def test_zero_means_healthy(self):
        self.assertEqual(self.flags(return_value=mock.Mock(stdout="throttled=0x0\n")), 0)

    def test_missing_tool_or_timeout_is_none(self):
        self.assertIsNone(self.flags(side_effect=FileNotFoundError()))
        self.assertIsNone(self.flags(side_effect=subprocess.TimeoutExpired("vcgencmd", 3)))

    def test_unparseable_output_is_none(self):
        for output in ("", "error", "throttled=zzz"):
            self.assertIsNone(self.flags(return_value=mock.Mock(stdout=output)), output)


class WatchdogCase(JobsCase):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.sleep = mock.Mock()
        self.cfg = make_cfg()
        self.dog = watchdog.Watchdog(lambda: self.cfg, self.clock, self.sleep)
        self.log = start_patch(self, watchdog, "log")
        self.submit = start_patch(self, jobs, "submit")
        self.disconnect = start_patch(self, session, "disconnect")
        self.any_active = start_patch(self, player, "any_active", return_value=True)
        self.sunshine_up = start_patch(self, pc, "sunshine_up", return_value=True)
        self.flags = start_patch(self, watchdog, "power_flags", return_value=0)
        self.iface = start_patch(self, watchdog, "default_interface", return_value="wlan0")
        self.rx = start_patch(self, watchdog, "rx_bytes", return_value=None)
        jobs.update(intent="up", request=dict(REQUEST))


class RxRateTests(WatchdogCase):
    def test_first_sample_has_no_rate(self):
        self.rx.return_value = 1000
        self.assertIsNone(self.dog.rx_rate(START))

    def test_rate_is_bytes_per_second_between_samples(self):
        self.rx.return_value = 1000
        self.dog.rx_rate(START)
        self.rx.return_value = 11000
        self.assertEqual(self.dog.rx_rate(START + 5), 2000)

    def test_unreadable_counter_resets_the_baseline(self):
        self.rx.return_value = 1000
        self.dog.rx_rate(START)
        self.rx.return_value = None
        self.assertIsNone(self.dog.rx_rate(START + 5))
        self.rx.return_value = 9000
        self.assertIsNone(self.dog.rx_rate(START + 10))

    def test_non_advancing_clock_yields_no_rate(self):
        self.rx.return_value = 1000
        self.dog.rx_rate(START)
        self.assertIsNone(self.dog.rx_rate(START))

    def test_reads_the_counter_of_the_default_interface(self):
        self.dog.rx_rate(START)
        self.rx.assert_called_once_with("wlan0")


class ProblemTests(WatchdogCase):
    def set_rate(self, rate):
        self.dog.rx_rate = mock.Mock(return_value=rate)

    def test_no_problem_when_everything_is_fine(self):
        self.set_rate(10**6)
        self.assertIsNone(self.dog.problem(self.cfg, START))

    def test_exited_stream_process_is_reported_at_once(self):
        self.any_active.return_value = False
        self.assertEqual(self.dog.problem(self.cfg, START), "the stream process exited")

    def test_offline_pc_is_tolerated_until_offline_seconds_pass(self):
        self.set_rate(None)
        self.sunshine_up.return_value = False
        self.assertIsNone(self.dog.problem(self.cfg, START))
        self.assertIsNone(self.dog.problem(self.cfg, START + watchdog.OFFLINE_SECONDS - 1))
        self.assertEqual(self.dog.problem(self.cfg, START + watchdog.OFFLINE_SECONDS), "the PC went offline")

    def test_pc_coming_back_restarts_the_offline_timer(self):
        self.set_rate(None)
        self.sunshine_up.return_value = False
        self.dog.problem(self.cfg, START)
        self.sunshine_up.return_value = True
        self.dog.problem(self.cfg, START + 5)
        self.sunshine_up.return_value = False
        self.assertIsNone(self.dog.problem(self.cfg, START + 6))
        self.assertIsNone(self.dog.problem(self.cfg, START + 6 + watchdog.OFFLINE_SECONDS - 1))

    def test_low_receive_rate_is_tolerated_until_stall_seconds_pass(self):
        self.set_rate(watchdog.MIN_RX_BYTES_PER_SECOND - 1)
        self.assertIsNone(self.dog.problem(self.cfg, START))
        self.assertIsNone(self.dog.problem(self.cfg, START + watchdog.STALL_SECONDS - 1))
        self.assertEqual(
            self.dog.problem(self.cfg, START + watchdog.STALL_SECONDS), "no video data is arriving"
        )

    def test_rate_at_the_threshold_is_not_a_stall(self):
        self.set_rate(watchdog.MIN_RX_BYTES_PER_SECOND)
        self.assertIsNone(self.dog.problem(self.cfg, START))
        self.assertIsNone(self.dog.problem(self.cfg, START + watchdog.STALL_SECONDS * 2))

    def test_recovered_rate_restarts_the_stall_timer(self):
        self.set_rate(0)
        self.dog.problem(self.cfg, START)
        self.set_rate(10**6)
        self.dog.problem(self.cfg, START + 10)
        self.set_rate(0)
        self.assertIsNone(self.dog.problem(self.cfg, START + 11))
        self.assertIsNone(self.dog.problem(self.cfg, START + 11 + watchdog.STALL_SECONDS - 1))

    def test_unknown_rate_is_never_a_stall(self):
        self.set_rate(None)
        self.assertIsNone(self.dog.problem(self.cfg, START))
        self.assertIsNone(self.dog.problem(self.cfg, START + 1000))

    def test_offline_pc_is_reported_before_a_stall(self):
        self.set_rate(0)
        self.sunshine_up.return_value = False
        self.dog.problem(self.cfg, START)
        reason = self.dog.problem(self.cfg, START + max(watchdog.OFFLINE_SECONDS, watchdog.STALL_SECONDS))
        self.assertEqual(reason, "the PC went offline")


class TickTests(WatchdogCase):
    def test_intent_down_takes_no_action_and_resets_timers(self):
        jobs.update(intent="down")
        self.any_active.return_value = False
        self.dog.offline_since = START
        self.dog.tick()
        self.submit.assert_not_called()
        self.assertIsNone(self.dog.offline_since)
        self.any_active.assert_not_called()

    def test_busy_job_lock_takes_no_action(self):
        self.any_active.return_value = False
        jobs._job_lock.acquire()
        self.dog.tick()
        self.submit.assert_not_called()
        self.sleep.assert_not_called()

    def test_healthy_stream_takes_no_action(self):
        self.dog.tick()
        self.submit.assert_not_called()
        self.sleep.assert_not_called()
        self.assertEqual(self.dog.healthy_since, START)

    def test_problem_triggers_a_reconnect_with_the_stored_request(self):
        self.any_active.return_value = False
        self.dog.tick()
        self.submit.assert_called_once_with(session.connect, self.cfg, "second", "tv", "Steam Big Picture")

    def test_config_is_read_from_the_provider_on_every_tick(self):
        seen = []
        self.dog.provider = lambda: seen.append(1) or self.cfg
        self.dog.tick()
        self.dog.tick()
        self.assertEqual(len(seen), 2)

    def test_attempts_are_cleared_after_healthy_reset_seconds(self):
        self.dog.attempts = [START - 10]
        self.dog.tick()
        self.assertEqual(self.dog.attempts, [START - 10])
        self.clock.now = START + watchdog.HEALTHY_RESET
        self.dog.tick()
        self.assertEqual(self.dog.attempts, [])

    def test_a_problem_restarts_the_healthy_timer(self):
        self.dog.tick()
        self.any_active.return_value = False
        self.clock.now = START + 10
        self.dog.tick()
        self.assertIsNone(self.dog.healthy_since)

    def test_power_status_change_is_logged_once(self):
        self.flags.return_value = 0x50005
        self.dog.tick()
        self.assertTrue(any("0x50005" in call.args[0] for call in self.log.call_args_list))
        self.log.reset_mock()
        self.clock.now = START + watchdog.POWER_CHECK_SECONDS
        self.dog.tick()
        self.log.assert_not_called()

    def test_power_is_checked_even_when_intent_is_down(self):
        jobs.update(intent="down")
        self.flags.return_value = 0x1
        self.dog.tick()
        self.assertTrue(any("0x1" in call.args[0] for call in self.log.call_args_list))


class PowerCheckTests(WatchdogCase):
    def test_checks_are_spaced_by_power_check_seconds(self):
        self.dog.check_power(START)
        self.dog.check_power(START + watchdog.POWER_CHECK_SECONDS - 1)
        self.assertEqual(self.flags.call_count, 1)
        self.dog.check_power(START + watchdog.POWER_CHECK_SECONDS)
        self.assertEqual(self.flags.call_count, 2)

    def test_unavailable_flags_are_ignored(self):
        self.flags.return_value = None
        self.dog.check_power(START)
        self.log.assert_not_called()


class ReconnectTests(WatchdogCase):
    def reconnect(self, reason="no video data is arriving"):
        self.dog.reconnect(self.cfg, dict(REQUEST), reason, self.clock())

    def test_sets_reconnecting_phase_then_sleeps_the_first_backoff(self):
        phases = []
        self.sleep.side_effect = lambda seconds: phases.append(jobs.snapshot()["phase"])
        self.reconnect()
        self.assertEqual(phases, ["reconnecting"])
        self.sleep.assert_called_once_with(watchdog.BACKOFF[0])

    def test_backoff_delays_are_5_15_45(self):
        self.assertEqual(watchdog.BACKOFF, (5, 15, 45))
        for step in range(len(watchdog.BACKOFF)):
            self.reconnect()
            self.clock.now += 1
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [5, 15, 45])

    def test_submits_connect_with_the_stored_request_after_the_sleep(self):
        order = mock.Mock()
        order.attach_mock(self.sleep, "sleep")
        order.attach_mock(self.submit, "submit")
        self.reconnect()
        self.assertEqual([call[0] for call in order.mock_calls], ["sleep", "submit"])
        self.submit.assert_called_once_with(session.connect, self.cfg, "second", "tv", "Steam Big Picture")

    def test_missing_request_fields_default_to_empty_strings(self):
        self.dog.reconnect(self.cfg, {}, "the stream process exited", self.clock())
        self.submit.assert_called_once_with(session.connect, self.cfg, "", "", "")

    def test_records_the_attempt_time_and_resets_detection_state(self):
        self.dog.offline_since = START
        self.dog.stalled_since = START
        self.reconnect()
        self.assertEqual(self.dog.attempts, [START])
        self.assertIsNone(self.dog.offline_since)
        self.assertIsNone(self.dog.stalled_since)

    def test_gives_up_after_three_attempts_inside_the_window(self):
        for _ in range(3):
            self.reconnect()
            self.clock.now += 10
        self.submit.reset_mock()
        self.sleep.reset_mock()
        self.reconnect("the PC went offline")
        self.submit.assert_not_called()
        self.sleep.assert_not_called()
        snap = jobs.snapshot()
        self.assertEqual(snap["intent"], "down")
        self.assertEqual(snap["phase"], "error")
        self.assertIn("the PC went offline", snap["error"])
        self.assertTrue(any("giving up" in call.args[0] for call in self.log.call_args_list))

    def test_old_attempts_expire_after_the_window(self):
        for _ in range(3):
            self.reconnect()
        self.clock.now = START + watchdog.WINDOW + 1
        self.submit.reset_mock()
        self.reconnect()
        self.submit.assert_called_once()
        self.assertEqual(self.sleep.call_args.args[0], watchdog.BACKOFF[0])

    def test_never_disconnects_even_when_giving_up(self):
        for _ in range(4):
            self.reconnect()
        self.disconnect.assert_not_called()

    def test_intent_changed_during_the_backoff_aborts_without_submitting(self):
        self.sleep.side_effect = lambda seconds: jobs.update(intent="down")
        self.reconnect()
        self.submit.assert_not_called()
        self.assertEqual(self.dog.attempts, [])

    def test_busy_submit_is_tolerated(self):
        self.submit.side_effect = jobs.Busy("another action is running")
        self.reconnect()
        self.assertEqual(len(self.dog.attempts), 1)

    def test_other_submit_errors_propagate(self):
        self.submit.side_effect = RuntimeError("kaput")
        with self.assertRaises(RuntimeError):
            self.reconnect()

    def test_giving_up_resets_the_detection_state(self):
        self.dog.attempts = [START] * 3
        self.dog.offline_since = START
        self.reconnect()
        self.assertIsNone(self.dog.offline_since)

    def test_first_reconnect_shows_reconnecting_phase_and_keeps_intent_up(self):
        self.reconnect()
        self.assertEqual(jobs.snapshot()["phase"], "reconnecting")
        self.assertEqual(jobs.snapshot()["intent"], "up")


class RunTests(WatchdogCase):
    class Stop(Exception):
        pass

    def test_ticks_after_sleeping_the_interval_and_survives_errors(self):
        calls = []

        def tick():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("tick broke")

        self.dog.tick = tick
        self.sleep.side_effect = [None, None, self.Stop()]
        with self.assertRaises(self.Stop):
            self.dog.run()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sleep.call_args_list[0].args[0], watchdog.INTERVAL)
        self.assertTrue(any("tick broke" in call.args[0] for call in self.log.call_args_list))


class StartTests(unittest.TestCase):
    def test_start_runs_the_watchdog_in_a_daemon_thread(self):
        ran = []
        fake = mock.Mock()
        fake.run.side_effect = lambda: ran.append(True)
        with mock.patch.object(watchdog, "Watchdog", return_value=fake) as factory:
            provider = mock.Mock()
            thread = watchdog.start(provider)
            thread.join(3)
        factory.assert_called_once_with(provider)
        self.assertTrue(thread.daemon)
        self.assertEqual(ran, [True])
        self.assertEqual(thread.name, "watchdog")

    def test_enabled_follows_the_watchdog_flag(self):
        self.assertTrue(watchdog.enabled(make_cfg(WATCHDOG="true")))
        self.assertTrue(watchdog.enabled(make_cfg(WATCHDOG="on")))
        self.assertFalse(watchdog.enabled(make_cfg(WATCHDOG="false")))
        self.assertFalse(watchdog.enabled(make_cfg(WATCHDOG="")))


if __name__ == "__main__":
    unittest.main()
