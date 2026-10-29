import threading
import unittest
from unittest import mock

from galaxy import config, jobs, obs, pc, player, session, sunshine, tv
from tests.helpers import JobsCase, make_cfg

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
            self.patch(module, name, getattr(self.m, name))
        self.patch(tv, "switch", self.m.tv_switch)
        self.patch(session.time, "sleep", self.m.sleep)

    def patch(self, module, name, replacement):
        patcher = mock.patch.object(module, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.m.write_session.assert_called_once_with(cfg, "Steam Big Picture", "tv", "3840x1080")
        self.m.control.assert_called_once_with("start", player.MOONLIGHT)
        self.m.confirm.assert_called_once_with(player.MOONLIGHT)
        self.m.tv_switch.assert_called_once_with(cfg, True)
        self.assertEqual(jobs.snapshot()["phase"], "streaming")
        self.assertEqual(jobs.snapshot()["source"], "main")

    def test_second_screen_uses_its_device_and_resolution(self):
        cfg = make_cfg()
        session.connect(cfg, "second", "both", "Desktop")
        self.m.select_output.assert_called_once_with(cfg, "dev-second")
        self.assertEqual(self.m.write_session.call_args.args[3], "1920x1080")

    def test_resolution_falls_back_to_1080p_when_not_configured(self):
        session.connect(make_cfg(DISPLAY_RES="main=3840x1080"), "second", "both", "Desktop")
        self.assertEqual(self.m.write_session.call_args.args[3], "1920x1080")

    def test_defaults_to_main_both_audio_and_default_app(self):
        session.connect(make_cfg(SUNSHINE_APP="Desktop"))
        self.m.select_output.assert_called_once_with(mock.ANY, "dev-main")
        self.assertEqual(self.m.write_session.call_args.args[1:3], ("Desktop", "both"))

    def test_reuses_saved_app_and_audio_when_not_given(self):
        self.m.read_session.return_value = {"app": "Steam Big Picture", "audio": "pc"}
        session.connect(make_cfg())
        self.assertEqual(self.m.write_session.call_args.args[1:3], ("Steam Big Picture", "pc"))

    def test_reuses_last_selected_source(self):
        jobs.update(source="second")
        session.connect(make_cfg())
        self.m.select_output.assert_called_once_with(mock.ANY, "dev-second")

    def test_waking_phase_is_announced_through_boot_callback(self):
        phases = []

        def boot(cfg, on_wait):
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

    def test_successful_connect_clears_old_warning(self):
        jobs.update(warning="old")
        session.connect(make_cfg(), "main", "", "")
        self.assertEqual(jobs.snapshot()["warning"], "")

    def test_waits_for_tv_thread_before_starting_player(self):
        gate = threading.Event()
        finished = []
        self.m.tv_switch.side_effect = lambda cfg, on: (gate.wait(0.05), finished.append(True))
        self.m.control.side_effect = lambda *args: self.assertEqual(finished, [True])
        session.connect(make_cfg(), "main", "", "")
        self.m.control.assert_called_once()

    def test_requires_pc_host(self):
        with self.assertRaisesRegex(RuntimeError, "PC_HOST"):
            session.connect(make_cfg(PC_HOST=""))
        self.m.stop_all.assert_not_called()

    def test_invalid_arguments_are_rejected_before_any_side_effect(self):
        with self.assertRaises(ValueError):
            session.connect(make_cfg(), "main", "loud", "")
        self.m.stop_all.assert_not_called()

    def test_unavailable_default_source_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "source 'main' is not available"):
            session.connect(make_cfg(DISPLAYS="other=dev"))
        self.m.stop_all.assert_not_called()

    def test_failure_releases_players_and_propagates(self):
        self.m.select_output.side_effect = RuntimeError("boom")
        with self.assertRaisesRegex(RuntimeError, "boom"):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.m.control.assert_not_called()
        self.assertNotEqual(jobs.snapshot()["phase"], "streaming")

    def test_boot_failure_propagates_and_cleans_up(self):
        self.m.boot.side_effect = RuntimeError("PC did not come up")
        with self.assertRaisesRegex(RuntimeError, "did not come up"):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)
        self.m.select_output.assert_not_called()

    def test_cleanup_failure_does_not_mask_original_error(self):
        self.m.confirm.side_effect = RuntimeError("exited right after starting")
        self.m.stop_all.side_effect = [None, OSError("cleanup broke")]
        with mock.patch.object(session, "log") as log:
            with self.assertRaisesRegex(RuntimeError, "exited right after starting"):
                session.connect(make_cfg(), "main", "", "")
        self.assertIn("cleanup broke", log.call_args.args[0])

    def test_keyboard_interrupt_also_triggers_cleanup(self):
        self.m.select_output.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            session.connect(make_cfg(), "main", "", "")
        self.assertEqual(self.m.stop_all.call_count, 2)


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

    def test_obs_failure_releases_players_and_ends_obs(self):
        self.m.begin.side_effect = RuntimeError("OBS is already streaming")
        with self.assertRaisesRegex(RuntimeError, "already streaming"):
            session.connect(self.cfg(), "obs", "", "")
        self.assertEqual(self.order()[-3:], ["begin", "stop_all", "end"])
        self.assertFalse(jobs.snapshot()["obs_active"])

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


class StatusTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.live = set()
        self.saved = {"app": "", "audio": ""}
        self.online = False
        self.output = "dev-second"
        for module, name, replacement in (
            (player, "active", lambda unit: unit in self.live),
            (player, "read_session", lambda: self.saved),
            (pc, "online", lambda cfg: self.online),
            (sunshine, "current_output", lambda cfg: self.output),
        ):
            patcher = mock.patch.object(module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def test_stream_ended_unexpectedly_becomes_error_phase(self):
        jobs.set_phase("streaming")
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["error"]), ("error", "The stream ended unexpectedly"))
        self.assertEqual(jobs.snapshot()["phase"], "error")

    def test_streaming_phase_is_kept_while_a_job_is_running(self):
        jobs.set_phase("streaming")
        jobs._job_lock.acquire()
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["busy"]), ("streaming", True))

    def test_live_stream_in_idle_phase_is_reported_as_streaming(self):
        self.live = {player.MOONLIGHT}
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["stream"]), ("streaming", True))

    def test_live_stream_clears_stale_error(self):
        jobs.set_phase("error", "old")
        self.live = {player.MOONLIGHT}
        result = session.status(make_cfg())
        self.assertEqual((result["phase"], result["error"]), ("streaming", ""))

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


if __name__ == "__main__":
    unittest.main()
