import subprocess
import unittest
from unittest import mock

from galaxy import tv
from tests.helpers import make_cfg


class ParsePowerTests(unittest.TestCase):
    def test_recognised_statuses(self):
        cases = {
            "power status: on": "on",
            "power status: standby": "standby",
            "power status: in transition from standby to on": "on",
            "power status: in transition from on to standby": "standby",
        }
        for line, expected in cases.items():
            self.assertEqual(tv.parse_power(line), expected, line)

    def test_finds_status_line_among_cec_noise(self):
        output = "opening a connection\nTRAFFIC: >> 10\npower status: standby\nclosing\n"
        self.assertEqual(tv.parse_power(output), "standby")

    def test_garbage_and_empty_output_are_unknown(self):
        for output in ("", "garbage", "power status: banana", "power status:", "xpower status: on"):
            self.assertEqual(tv.parse_power(output), "unknown", output)


class CecTests(unittest.TestCase):
    def test_sends_command_on_stdin_and_decodes_stdout(self):
        done = mock.Mock(stdout=b"power status: on\n")
        with mock.patch.object(tv.subprocess, "run", return_value=done) as run:
            self.assertEqual(tv.cec(make_cfg(CEC_DEVICE="/dev/cec9"), "pow 0"), "power status: on\n")
        self.assertEqual(run.call_args.args[0][-1], "/dev/cec9")
        self.assertEqual(run.call_args.kwargs["input"], b"pow 0")

    def test_failures_yield_empty_output_and_are_logged(self):
        for error in (FileNotFoundError("no cec-client"), subprocess.TimeoutExpired("cec-client", 25)):
            with mock.patch.object(tv.subprocess, "run", side_effect=error):
                with mock.patch.object(tv, "log") as log:
                    self.assertEqual(tv.cec(make_cfg(), "pow 0"), "")
            log.assert_called_once()
            self.assertIn("cec-client failed", log.call_args.args[0])



class SwitchTests(unittest.TestCase):
    def setUp(self):
        cec = mock.patch.object(tv, "cec")
        sleep = mock.patch.object(tv.time, "sleep")
        self.cec, self.sleep = cec.start(), sleep.start()
        self.addCleanup(cec.stop)
        self.addCleanup(sleep.stop)

    def states(self, *states):
        patcher = mock.patch.object(tv, "power_state", side_effect=list(states))
        self.power_state = patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_cec_reports_success_without_touching_tv(self):
        self.states()
        self.assertTrue(tv.switch(make_cfg(TV_CEC="false"), True))
        self.cec.assert_not_called()
        self.power_state.assert_not_called()

    def test_returns_true_when_already_in_wanted_state(self):
        self.states("on")
        self.assertTrue(tv.switch(make_cfg(), True))
        self.cec.assert_not_called()
        self.sleep.assert_not_called()

    def test_already_in_standby_when_turning_off(self):
        self.states("standby")
        self.assertTrue(tv.switch(make_cfg(), False))
        self.cec.assert_not_called()

    def test_sends_on_command_and_succeeds_on_retry(self):
        self.states("standby", "on")
        self.assertTrue(tv.switch(make_cfg(), True))
        self.cec.assert_called_once_with(mock.ANY, "on 0")
        self.sleep.assert_called_once_with(6)

    def test_sends_standby_command_when_turning_off(self):
        self.states("on", "standby")
        self.assertTrue(tv.switch(make_cfg(), False))
        self.cec.assert_called_once_with(mock.ANY, "standby 0")

    def test_retries_attempts_times_then_reports_failure(self):
        self.states(*["standby"] * (tv.ATTEMPTS + 1))
        self.assertFalse(tv.switch(make_cfg(), True))
        self.assertEqual(self.cec.call_count, tv.ATTEMPTS)

    def test_sleeps_between_attempts_and_once_before_the_final_check_only(self):
        self.states(*["standby"] * (tv.ATTEMPTS + 1))
        tv.switch(make_cfg(), True)
        self.assertEqual(self.sleep.call_args_list, [mock.call(tv.SETTLE_SECONDS)] * tv.ATTEMPTS)

    def test_no_sleep_after_the_last_failed_attempt_besides_the_settle(self):
        self.states(*["standby"] * (tv.ATTEMPTS + 1))
        order = mock.Mock()
        order.attach_mock(self.cec, "cec")
        order.attach_mock(self.sleep, "sleep")
        tv.switch(make_cfg(), True)
        names = [call[0] for call in order.mock_calls]
        self.assertEqual(names[-2:], ["cec", "sleep"])
        self.assertEqual(names.count("sleep"), tv.ATTEMPTS)

    def test_final_check_can_still_succeed_after_last_attempt(self):
        self.states(*["unknown"] * tv.ATTEMPTS, "on")
        self.assertTrue(tv.switch(make_cfg(), True))
        self.assertEqual(self.cec.call_count, tv.ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
