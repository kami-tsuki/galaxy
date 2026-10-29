import threading
import unittest
from unittest import mock

from galaxy import jobs, obs, pc, player, session, sunshine, tv
from tests.helpers import JobsCase, make_cfg, start_patch, wait_idle

STEPS = ("stop_all", "boot", "select_output", "write_session", "control", "confirm", "begin", "end")
OBS_CFG = {"OBS_ENABLED": "true", "OBS_PASS": "x"}


class ValidateTests(unittest.TestCase):
    def test_accepts_empty_and_valid_values(self):
        session.validate(make_cfg(**OBS_CFG), "", "", "")
        session.validate(make_cfg(**OBS_CFG), "second", "pc", "Steam Big Picture")
        session.validate(make_cfg(**OBS_CFG), "obs", "tv", "Desktop")

    def test_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "unknown source 'tv'.*main, second"):
            session.validate(make_cfg(), "tv", "", "")

    def test_obs_is_unknown_when_disabled(self):
        with self.assertRaisesRegex(ValueError, "unknown source"):
            session.validate(make_cfg(), "obs", "", "")

    def test_rejects_unknown_audio_mode(self):
        with self.assertRaisesRegex(ValueError, "unknown audio mode"):
            session.validate(make_cfg(), "", "loud", "")

    def test_rejects_unknown_app(self):
        with self.assertRaisesRegex(ValueError, "unknown app"):
            session.validate(make_cfg(), "", "", "Calculator")

    def test_no_sources_configured_message(self):
        with self.assertRaisesRegex(ValueError, "none configured"):
            session.validate(make_cfg(DISPLAYS=""), "main", "", "")


class ResolveTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.saved = start_patch(self, player, "read_session", return_value={"app": "", "audio": ""})

    def test_defaults_to_main_both_audio_and_configured_app(self):
        self.assertEqual(session.resolve(make_cfg()), ("main", "both", "Desktop"))

    def test_explicit_values_win_over_saved_and_defaults(self):
        self.saved.return_value = {"app": "Desktop", "audio": "pc"}
        result = session.resolve(make_cfg(), "second", "tv", "Steam Big Picture")
        self.assertEqual(result, ("second", "tv", "Steam Big Picture"))

    def test_saved_app_and_audio_are_reused(self):
        self.saved.return_value = {"app": "Steam Big Picture", "audio": "pc"}
        self.assertEqual(session.resolve(make_cfg()), ("main", "pc", "Steam Big Picture"))

    def test_last_selected_source_is_reused(self):
        jobs.update(source="second")
        self.assertEqual(session.resolve(make_cfg())[0], "second")

    def test_falls_back_to_first_source_when_main_is_missing(self):
        self.assertEqual(session.resolve(make_cfg(DISPLAYS="left=1,right=2"))[0], "left")

    def test_invalid_values_raise_value_error(self):
        for args in (("tv",), ("", "loud"), ("", "", "Calc")):
            with self.assertRaises(ValueError):
                session.resolve(make_cfg(), *args)

    def test_no_displays_and_no_obs_raises_no_source(self):
        with self.assertRaisesRegex(ValueError, "no source is configured"):
            session.resolve(make_cfg(DISPLAYS=""))

    def test_remembered_source_that_is_gone_raises_not_available(self):
        jobs.update(source="second")
        with self.assertRaisesRegex(ValueError, "source 'second' is not available"):
            session.resolve(make_cfg(DISPLAYS="main=dev-main"))

    def test_missing_pc_host_is_a_value_error(self):
        with self.assertRaisesRegex(ValueError, "PC_HOST"):
            session.resolve(make_cfg(PC_HOST=""))

    def test_missing_sunshine_user_is_a_value_error_for_screens(self):
        with self.assertRaisesRegex(ValueError, "SUNSHINE_USER"):
            session.resolve(make_cfg(SUNSHINE_USER=""), "main")

    def test_obs_source_does_not_need_sunshine_user(self):
        cfg = make_cfg(SUNSHINE_USER="", **OBS_CFG)
        self.assertEqual(session.resolve(cfg, "obs")[0], "obs")

    def test_obs_source_still_needs_pc_host(self):
        with self.assertRaisesRegex(ValueError, "PC_HOST"):
            session.resolve(make_cfg(PC_HOST="", **OBS_CFG), "obs")


class ConnectCase(JobsCase):
    def setUp(self):
        super().setUp()
        self.m = mock.Mock()
        self.m.read_session.return_value = {"app": "", "audio": ""}
        self.m.active.return_value = False
        self.m.sunshine_up.return_value = True
        self.m.local_address.return_value = "10.0.0.5"
        self.m.tv_switch.return_value = True
        targets = {
            "stop_all": player,
            "control": player,
            "confirm": player,
            "write_session": player,
            "read_session": player,
            "active": player,
            "boot": pc,
            "local_address": pc,
            "sunshine_up": pc,
            "select_output": sunshine,
            "begin": obs,
            "end": obs,
        }
        for name, module in targets.items():
            start_patch(self, module, name, new=getattr(self.m, name))
        start_patch(self, tv, "switch", new=self.m.tv_switch)
        start_patch(self, session.time, "sleep", new=self.m.sleep)
        self.log = start_patch(self, session, "log")

    def order(self):
        return [call[0] for call in self.m.mock_calls if call[0] in STEPS]


class ConnectScreenTests(ConnectCase):
    def test_orchestrates_steps_in_order_with_device_and_resolution(self):
        cfg = make_cfg()
        session.connect(cfg, "main", "tv", "Steam Big Picture")
        self.assertEqual(
            self.order(), ["stop_all", "boot", "select_output", "write_session", "control", "confirm"]
        )
        self.m.select_output.assert_called_once_with(cfg, "dev-main")
        self.m.write_session.assert_called_once_with("Steam Big Picture", "tv", "3840x1080")
        self.m.control.assert_called_once_with("start", player.MOONLIGHT)
        self.m.confirm.assert_called_once_with(player.MOONLIGHT)
        self.m.tv_switch.assert_called_once_with(cfg, True)
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["source"]), ("streaming", "main"))

    def test_second_screen_uses_its_device_and_resolution(self):
        cfg = make_cfg()
        session.connect(cfg, "second", "both", "Desktop")
        self.m.select_output.assert_called_once_with(cfg, "dev-second")
        self.assertEqual(self.m.write_session.call_args.args[2], "1920x1080")

    def test_resolution_falls_back_to_1080p_when_not_configured(self):
        session.connect(make_cfg(DISPLAY_RES="main=3840x1080"), "second", "both", "Desktop")
        self.assertEqual(self.m.write_session.call_args.args[2], "1920x1080")

    def test_defaults_to_main_both_audio_and_default_app(self):
        session.connect(make_cfg(SUNSHINE_APP="Desktop"))
        self.m.select_output.assert_called_once_with(mock.ANY, "dev-main")
        self.assertEqual(self.m.write_session.call_args.args[:2], ("Desktop", "both"))

    def test_reuses_saved_app_and_audio_when_not_given(self):
        self.m.read_session.return_value = {"app": "Steam Big Picture", "audio": "pc"}
        session.connect(make_cfg())
        self.assertEqual(self.m.write_session.call_args.args[:2], ("Steam Big Picture", "pc"))

    def test_reuses_last_selected_source(self):
        jobs.update(source="second")
        session.connect(make_cfg())
        self.m.select_output.assert_called_once_with(mock.ANY, "dev-second")

    def test_sets_intent_up_and_stores_resolved_request(self):
        session.connect(make_cfg(), "second", "", "")
        snap = jobs.snapshot()
        self.assertEqual(snap["intent"], "up")
        self.assertEqual(snap["request"], {"source": "second", "audio": "both", "app": "Desktop"})

    def test_intent_is_already_up_while_the_stream_is_starting(self):
        seen = []
        self.m.select_output.side_effect = lambda cfg, device: seen.append(jobs.snapshot()["intent"])
        session.connect(make_cfg(), "main", "", "")
        self.assertEqual(seen, ["up"])

    def test_clears_a_stale_cancel_request_at_the_start(self):
        jobs.request_cancel()
        session.connect(make_cfg(), "main", "", "")
        self.assertFalse(jobs.cancelled())
        self.assertEqual(jobs.snapshot()["phase"], "streaming")

    def test_boot_receives_cancel_check_and_waking_callback(self):
        phases = []

        def boot(cfg, on_wait, stop):
            self.assertIs(stop, jobs.cancelled)
            on_wait()
            phases.append(jobs.snapshot()["phase"])

        self.m.boot.side_effect = boot
        session.connect(make_cfg(), "main", "", "")
        self.assertEqual(phases, ["waking"])

    def test_tv_failure_sets_warning_but_stream_succeeds(self):
        self.m.tv_switch.return_value = False
        session.connect(make_cfg(), "main", "", "")
        snap = jobs.snapshot()
        self.assertEqual(snap["phase"], "streaming")
        self.assertIn("TV did not confirm", snap["warning"])

    def test_tv_exception_is_logged_and_reported_as_warning_without_failing(self):
        self.m.tv_switch.side_effect = OSError("cec gone")
        session.connect(make_cfg(), "main", "", "")
        snap = jobs.snapshot()
        self.assertEqual(snap["phase"], "streaming")
        self.assertIn("TV did not confirm", snap["warning"])
        self.assertTrue(any("cec gone" in call.args[0] for call in self.log.call_args_list))

    def test_successful_connect_clears_old_warning(self):
        jobs.update(warning="old")
        session.connect(make_cfg(), "main", "", "")
        self.assertEqual(jobs.snapshot()["warning"], "")

    def test_waits_for_tv_thread_before_starting_player(self):
        gate = threading.Event()
        finished = []
        self.m.tv_switch.side_effect = lambda cfg, on: (gate.wait(3), finished.append(True))
        self.m.select_output.side_effect = lambda cfg, device: gate.set()
        self.m.control.side_effect = lambda *args: self.assertEqual(finished, [True])
        session.connect(make_cfg(), "main", "", "")
        self.m.control.assert_called_once()

    def test_invalid_arguments_are_rejected_before_any_side_effect(self):
        with self.assertRaises(ValueError):
            session.connect(make_cfg(), "main", "loud", "")
        self.m.stop_all.assert_not_called()
        self.assertEqual(jobs.snapshot()["intent"], "down")

    def test_missing_pc_host_is_rejected_before_any_side_effect(self):
        with self.assertRaisesRegex(ValueError, "PC_HOST"):
            session.connect(make_cfg(PC_HOST=""))
        self.m.stop_all.assert_not_called()
        self.assertEqual(jobs.snapshot()["request"], {})

    def test_unavailable_remembered_source_is_rejected(self):
        jobs.update(source="gone")
        with self.assertRaisesRegex(ValueError, "source 'gone' is not available"):
            session.connect(make_cfg())
        self.m.stop_all.assert_not_called()

    def test_failure_releases_players_sets_intent_down_and_propagates(self):
        self.m.select_output.side_effect = RuntimeError("boom")
        with self.assertRaisesRegex(RuntimeError, "boom"):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.m.control.assert_not_called()
        snap = jobs.snapshot()
        self.assertNotEqual(snap["phase"], "streaming")
        self.assertEqual(snap["intent"], "down")

    def test_boot_failure_propagates_and_cleans_up(self):
        self.m.boot.side_effect = RuntimeError("PC did not come up")
        with self.assertRaisesRegex(RuntimeError, "did not come up"):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.m.select_output.assert_not_called()

    def test_cleanup_failure_does_not_mask_original_error(self):
        self.m.confirm.side_effect = RuntimeError("exited right after starting")
        self.m.stop_all.side_effect = [None, OSError("cleanup broke")]
        with self.assertRaisesRegex(RuntimeError, "exited right after starting"):
            session.connect(make_cfg(), "main", "", "")
        self.assertIn("cleanup broke", self.log.call_args.args[0])

    def test_keyboard_interrupt_also_triggers_cleanup(self):
        self.m.select_output.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.assertEqual(jobs.snapshot()["intent"], "down")


class ConnectCancelTests(ConnectCase):
    def test_cancel_during_boot_stops_before_selecting_the_output(self):
        self.m.boot.side_effect = lambda cfg, on_wait, stop: jobs.request_cancel()
        with self.assertRaises(jobs.Cancelled):
            session.connect(make_cfg(), "main", "", "")
        self.m.select_output.assert_not_called()
        self.m.control.assert_not_called()
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.assertEqual(jobs.snapshot()["intent"], "down")

    def test_cancel_after_output_selection_stops_before_writing_the_session(self):
        self.m.select_output.side_effect = lambda cfg, device: jobs.request_cancel()
        with self.assertRaises(jobs.Cancelled):
            session.connect(make_cfg(), "main", "", "")
        self.m.write_session.assert_not_called()
        self.m.control.assert_not_called()

    def test_cancel_while_waiting_for_the_tv_stops_before_starting_the_player(self):
        self.m.write_session.side_effect = lambda *args: jobs.request_cancel()
        with self.assertRaises(jobs.Cancelled):
            session.connect(make_cfg(), "main", "", "")
        self.m.control.assert_not_called()
        self.assertNotEqual(jobs.snapshot()["phase"], "streaming")

    def test_cancel_before_obs_receiver_start_does_not_start_it(self):
        self.m.boot.side_effect = lambda cfg, on_wait, stop: jobs.request_cancel()
        with self.assertRaises(jobs.Cancelled):
            session.connect(make_cfg(**OBS_CFG), "obs", "", "")
        self.m.control.assert_not_called()
        self.m.begin.assert_not_called()

    def test_cancelled_connect_run_as_a_job_leaves_no_error_phase(self):
        self.m.boot.side_effect = lambda cfg, on_wait, stop: jobs.request_cancel()
        jobs.submit(session.connect, make_cfg(), "main", "", "")
        self.assertTrue(wait_idle())
        self.assertNotEqual(jobs.snapshot()["phase"], "error")


class ConnectObsTests(ConnectCase):
    def cfg(self, **extra):
        return make_cfg(SRT_PORT="9100", **OBS_CFG, **extra)

    def test_starts_receiver_before_obs_with_srt_url(self):
        cfg = self.cfg()
        session.connect(cfg, "obs", "", "")
        self.assertEqual(self.order(), ["stop_all", "boot", "control", "confirm", "begin", "confirm"])
        self.m.control.assert_called_once_with("start", player.OBS)
        self.m.begin.assert_called_once_with(cfg, "srt://10.0.0.5:9100?mode=caller&pkt_size=1316")
        self.assertEqual([call.args for call in self.m.confirm.call_args_list], [(player.OBS, 4), (player.OBS, 6)])
        self.m.select_output.assert_not_called()
        self.m.write_session.assert_not_called()
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["source"], snap["obs_active"]), ("streaming", "obs", True))

    def test_obs_works_without_displays_or_sunshine_user(self):
        session.connect(self.cfg(DISPLAYS="", SUNSHINE_USER=""), "obs", "", "")
        self.assertEqual(jobs.snapshot()["phase"], "streaming")

    def test_obs_failure_releases_players_and_ends_obs(self):
        self.m.begin.side_effect = RuntimeError("OBS is already streaming")
        with self.assertRaisesRegex(RuntimeError, "already streaming"):
            session.connect(self.cfg(), "obs", "", "")
        self.assertEqual(self.order()[-3:], ["begin", "stop_all", "end"])
        self.assertFalse(jobs.snapshot()["obs_active"])
        self.assertEqual(jobs.snapshot()["intent"], "down")

    def test_receiver_failure_before_obs_begin_does_not_touch_obs(self):
        self.m.confirm.side_effect = RuntimeError("receiver exited")
        with self.assertRaises(RuntimeError):
            session.connect(self.cfg(), "obs", "", "")
        self.m.begin.assert_not_called()

    def test_switching_away_from_obs_ends_obs_session_first(self):
        jobs.update(obs_active=True)
        cfg = self.cfg()
        session.connect(cfg, "main", "", "")
        self.m.end.assert_called_once_with(cfg)
        self.assertEqual(self.order()[:3], ["stop_all", "boot", "end"])
        self.assertFalse(jobs.snapshot()["obs_active"])

    def test_obs_source_is_unavailable_when_obs_disabled(self):
        with self.assertRaises(ValueError):
            session.connect(make_cfg(), "obs", "", "")


class ReleaseTests(ConnectCase):
    def test_release_without_obs_only_stops_players(self):
        session.release(make_cfg())
        self.m.stop_all.assert_called_once()
        self.m.end.assert_not_called()

    def test_release_ends_obs_when_active_and_pc_up(self):
        jobs.update(obs_active=True)
        cfg = make_cfg(**OBS_CFG)
        session.release(cfg)
        self.m.end.assert_called_once_with(cfg)

    def test_release_skips_obs_end_when_pc_is_down(self):
        jobs.update(obs_active=True)
        self.m.sunshine_up.return_value = False
        session.release(make_cfg(**OBS_CFG))
        self.m.end.assert_not_called()
        self.assertFalse(jobs.snapshot()["obs_active"])

    def test_release_detects_obs_through_running_unit(self):
        self.m.active.side_effect = lambda unit: unit == player.OBS
        session.release(make_cfg(**OBS_CFG))
        self.m.end.assert_called_once()


class DisconnectTests(ConnectCase):
    def test_turns_tv_off_when_enabled_and_ends_idle(self):
        cfg = make_cfg(TV_OFF_ON_STOP="true")
        session.disconnect(cfg)
        self.m.stop_all.assert_called_once()
        self.m.tv_switch.assert_called_once_with(cfg, False)
        self.assertEqual(jobs.snapshot()["phase"], "idle")

    def test_leaves_tv_alone_when_disabled(self):
        session.disconnect(make_cfg(TV_OFF_ON_STOP="false"))
        self.m.stop_all.assert_called_once()
        self.m.tv_switch.assert_not_called()
        self.assertEqual(jobs.snapshot()["phase"], "idle")

    def test_stopping_phase_is_visible_while_releasing(self):
        seen = []
        self.m.stop_all.side_effect = lambda: seen.append(jobs.snapshot()["phase"])
        session.disconnect(make_cfg())
        self.assertEqual(seen, ["stopping"])

    def test_sets_intent_down_before_releasing(self):
        jobs.update(intent="up")
        seen = []
        self.m.stop_all.side_effect = lambda: seen.append(jobs.snapshot()["intent"])
        session.disconnect(make_cfg())
        self.assertEqual(seen, ["down"])

    def test_clears_the_cancel_request_so_the_cleanup_runs_to_the_end(self):
        jobs.request_cancel()
        session.disconnect(make_cfg())
        self.assertFalse(jobs.cancelled())
        self.assertEqual(jobs.snapshot()["phase"], "idle")


class StatusTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.live = set()
        self.saved = {"app": "", "audio": ""}
        self.online = False
        self.output = "dev-second"
        start_patch(self, player, "active", new=lambda unit: unit in self.live)
        start_patch(self, player, "read_session", new=lambda: self.saved)
        start_patch(self, pc, "online", new=lambda cfg: self.online)
        start_patch(self, sunshine, "current_output", new=lambda cfg: self.output)

    def test_idle_shape_and_defaults(self):
        result = session.status(make_cfg(**OBS_CFG))
        self.assertEqual(
            result,
            {
                "phase": "idle",
                "error": "",
                "warning": "",
                "stream": False,
                "busy": False,
                "pc_online": False,
                "pc_host": "192.0.2.10",
                "source": "",
                "sources": ["main", "second", "obs"],
                "app": "Desktop",
                "apps": ["Desktop", "Steam Big Picture"],
                "audio": "both",
                "audio_modes": ["both", "tv", "pc"],
            },
        )

    def test_stream_ended_unexpectedly_is_shown_as_error_without_changing_state(self):
        jobs.set_phase("streaming")
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["error"]), ("error", "The stream ended unexpectedly"))
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("streaming", ""))

    def test_live_stream_after_error_is_shown_as_streaming_without_changing_state(self):
        jobs.set_phase("error", "old")
        self.live = {player.MOONLIGHT}
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["error"]), ("streaming", ""))
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("error", "old"))

    def test_status_does_not_touch_intent_or_request(self):
        jobs.update(intent="up", request={"source": "main"})
        session.status(make_cfg())
        snap = jobs.snapshot()
        self.assertEqual((snap["intent"], snap["request"]), ("up", {"source": "main"}))

    def test_streaming_phase_is_kept_while_a_job_is_running(self):
        jobs.set_phase("streaming")
        jobs._job_lock.acquire()
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["busy"]), ("streaming", True))

    def test_live_stream_in_idle_phase_is_reported_as_streaming(self):
        self.live = {player.MOONLIGHT}
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["stream"]), ("streaming", True))

    def test_error_phase_persists_without_live_stream(self):
        jobs.set_phase("error", "boom")
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["error"]), ("error", "boom"))

    def test_receiver_active_reports_obs_source(self):
        self.live = {player.OBS}
        self.online = True
        self.assertEqual(session.status(make_cfg(**OBS_CFG))["source"], "obs")

    def test_busy_reports_source_from_state(self):
        jobs.update(source="main")
        self.online = True
        jobs._job_lock.acquire()
        self.assertEqual(session.status(make_cfg())["source"], "main")

    def test_online_pc_reports_screen_matching_sunshine_output(self):
        jobs.update(source="main")
        self.online = True
        self.assertEqual(session.status(make_cfg())["source"], "second")

    def test_online_pc_with_unknown_output_has_no_source(self):
        self.online, self.output = True, "dev-unknown"
        self.assertEqual(session.status(make_cfg())["source"], "")

    def test_online_pc_keeps_chosen_source_when_output_unreadable(self):
        jobs.update(source="main")
        self.online, self.output = True, None
        self.assertEqual(session.status(make_cfg())["source"], "main")

    def test_offline_pc_reports_source_from_state(self):
        jobs.update(source="second")
        self.assertEqual(session.status(make_cfg())["source"], "second")

    def test_saved_app_and_audio_are_reported(self):
        self.saved = {"app": "Steam Big Picture", "audio": "pc"}
        result = session.status(make_cfg())
        self.assertEqual((result["app"], result["audio"]), ("Steam Big Picture", "pc"))


class LivenessTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.active = start_patch(self, player, "active", return_value=False)
        self.clock = start_patch(self, jobs.time, "time", return_value=100.0)

    def test_liveness_reports_both_units(self):
        self.active.side_effect = lambda unit: unit == player.OBS
        self.assertEqual(session.liveness(), (False, True))

    def test_liveness_is_cached_within_the_ttl(self):
        session.liveness()
        self.clock.return_value = 100.0 + session.LIVENESS_TTL / 2
        session.liveness()
        self.assertEqual(self.active.call_count, 2)

    def test_liveness_is_refreshed_after_the_ttl(self):
        session.liveness()
        self.clock.return_value = 100.0 + session.LIVENESS_TTL + 0.1
        session.liveness()
        self.assertEqual(self.active.call_count, 4)

    def test_status_calls_reuse_the_cached_liveness(self):
        start_patch(self, pc, "online", return_value=False)
        start_patch(self, player, "read_session", return_value={"app": "", "audio": ""})
        session.status(make_cfg())
        session.status(make_cfg())
        self.assertEqual(self.active.call_count, 2)


class SwitchTvTests(unittest.TestCase):
    def test_records_the_switch_result(self):
        outcome = {}
        with mock.patch.object(tv, "switch", return_value=True):
            session.switch_tv(make_cfg(), outcome)
        self.assertEqual(outcome, {"ok": True})

    def test_exception_is_logged_and_recorded_as_not_ok(self):
        outcome = {}
        with mock.patch.object(tv, "switch", side_effect=RuntimeError("cec")):
            with mock.patch.object(session, "log") as log:
                session.switch_tv(make_cfg(), outcome)
        self.assertEqual(outcome, {"ok": False})
        self.assertIn("cec", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
