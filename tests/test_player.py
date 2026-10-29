import itertools
import os
import unittest
from pathlib import Path
from unittest import mock

from galaxy import player
from tests.helpers import TempDirCase, start_patch


class SessionFileCase(TempDirCase):
    def setUp(self):
        super().setUp()
        self.path = self.dir / "run" / "session.env"


class WriteSessionTests(SessionFileCase):
    def test_round_trips_every_audio_mode(self):
        for mode in player.AUDIO_MODES:
            player.write_session("Steam Big Picture", mode, "3840x1080", self.path)
            self.assertEqual(player.read_session(self.path), {"app": "Steam Big Picture", "audio": mode})

    def test_file_content_has_flags_driver_and_resolution(self):
        player.write_session("Desktop", "tv", "1920x1080", self.path)
        self.assertEqual(
            self.path.read_text(),
            'SUNSHINE_APP="Desktop"\nAUDIO_FLAGS="--no-audio-on-host"\nAUDIO_DRIVER=pulseaudio\n'
            'RESOLUTION_FLAGS="--resolution 1920x1080"\n',
        )

    def test_audio_modes_map_to_expected_drivers(self):
        drivers = {mode: driver for mode, (_, driver) in player.AUDIO_MODES.items()}
        self.assertEqual(drivers, {"both": "pulseaudio", "tv": "pulseaudio", "pc": "dummy"})

    def test_creates_missing_parent_directory(self):
        player.write_session("Desktop", "both", "1920x1080", self.path)
        self.assertTrue(self.path.is_file())

    def test_app_is_not_checked_against_the_configured_list(self):
        player.write_session("Anything Else", "both", "1920x1080", self.path)
        self.assertEqual(player.read_session(self.path)["app"], "Anything Else")

    def test_default_path_is_the_session_path(self):
        target = self.dir / "default.env"
        with mock.patch.object(player, "session_path", return_value=target):
            player.write_session("Desktop", "pc", "1920x1080")
        self.assertEqual(player.read_session(target), {"app": "Desktop", "audio": "pc"})

    def assert_rejected(self, app="Desktop", audio="both", resolution="1920x1080", message=""):
        with self.assertRaisesRegex(ValueError, message):
            player.write_session(app, audio, resolution, self.path)
        self.assertFalse(self.path.exists())

    def test_rejects_unknown_audio_mode(self):
        self.assert_rejected(audio="surround", message="audio mode")

    def test_rejects_bad_resolutions(self):
        for resolution in ("", "1920", "1920x", "x1080", "19x10", "123456x1080", "1920x1080 --evil", "1920x1080\n"):
            self.assert_rejected(resolution=resolution, message="resolution")

    def test_rejects_dangerous_app_names(self):
        for app in ('A"b', "A\\b", "A$b", "A\nb", "-flag"):
            self.assert_rejected(app=app, message="invalid app name")


class ReadSessionTests(SessionFileCase):
    def test_missing_file_yields_empty_values(self):
        self.assertEqual(player.read_session(self.path), {"app": "", "audio": ""})

    def test_unrecognised_audio_flags_yield_empty_audio(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('SUNSHINE_APP="X"\nAUDIO_FLAGS="--foo"\nAUDIO_DRIVER=pulseaudio\n')
        self.assertEqual(player.read_session(self.path), {"app": "X", "audio": ""})

    def test_driver_distinguishes_modes_with_equal_flags(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('AUDIO_FLAGS="--audio-on-host"\nAUDIO_DRIVER=dummy\n')
        self.assertEqual(player.read_session(self.path)["audio"], "pc")

    def test_default_path_uses_user_runtime_dir(self):
        with mock.patch.object(os, "getuid", create=True, return_value=1234):
            self.assertEqual(player.session_path(), Path("/run/user/1234/galaxy-session.env"))


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.run = start_patch(self, player.subprocess, "run")
        self.euid = start_patch(self, os, "geteuid", create=True, return_value=1000)
        self.log = start_patch(self, player, "log")
        self.run.return_value = mock.Mock(returncode=0, stderr="")

    def test_non_root_uses_sudo(self):
        player.control("stop", "u.service")
        self.assertEqual(self.run.call_args.args[0], ["sudo", "-n", "systemctl", "stop", "u.service"])

    def test_root_skips_sudo(self):
        self.euid.return_value = 0
        player.control("start", "u.service")
        self.assertEqual(self.run.call_args.args[0], ["systemctl", "start", "u.service"])

    def test_start_failure_raises_with_stderr(self):
        self.run.return_value = mock.Mock(returncode=1, stderr=" Unit not found\n")
        with self.assertRaisesRegex(RuntimeError, "Unit not found"):
            player.control("start", "u.service")

    def test_start_failure_without_stderr_names_the_command(self):
        self.run.return_value = mock.Mock(returncode=1, stderr="")
        with self.assertRaisesRegex(RuntimeError, "systemctl start u.service failed"):
            player.control("start", "u.service")

    def test_stop_failure_is_logged_not_raised(self):
        self.run.return_value = mock.Mock(returncode=1, stderr="busy")
        player.control("stop", "u.service")
        self.log.assert_called_once_with("busy")

    def test_stop_failure_without_stderr_logs_default_message(self):
        self.run.return_value = mock.Mock(returncode=1, stderr="")
        player.control("stop", "u.service")
        self.log.assert_called_once_with("systemctl stop u.service failed")

    def test_success_logs_nothing(self):
        player.control("stop", "u.service")
        self.log.assert_not_called()


class ActiveAndStopAllTests(unittest.TestCase):
    def test_active_reflects_exit_code(self):
        with mock.patch.object(player.subprocess, "run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(player.active("u"))
        with mock.patch.object(player.subprocess, "run", return_value=mock.Mock(returncode=3)):
            self.assertFalse(player.active("u"))

    def test_any_active_is_true_when_either_unit_runs(self):
        for running in (player.MOONLIGHT, player.OBS):
            with mock.patch.object(player, "active", side_effect=lambda unit: unit == running):
                self.assertTrue(player.any_active(), running)

    def test_any_active_is_false_when_no_unit_runs(self):
        with mock.patch.object(player, "active", return_value=False):
            self.assertFalse(player.any_active())

    def test_stop_all_stops_only_active_units(self):
        with mock.patch.object(player, "active", side_effect=lambda unit: unit == player.OBS):
            with mock.patch.object(player, "control") as control:
                player.stop_all()
        control.assert_called_once_with("stop", player.OBS)


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.sleep = start_patch(self, player.time, "sleep")

    def test_raises_when_unit_exits(self):
        with mock.patch.object(player, "active", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "galaxy-stream.service exited right after starting"):
                player.confirm(player.MOONLIGHT)

    def test_raises_when_unit_dies_part_way_through(self):
        with mock.patch.object(player, "active", side_effect=[True, True, False]):
            with mock.patch.object(player.time, "time", side_effect=itertools.count(0, 1)):
                with self.assertRaises(RuntimeError):
                    player.confirm(player.OBS, 10)
        self.assertEqual(self.sleep.call_count, 2)

    def test_returns_when_unit_stays_up_for_the_whole_period(self):
        with mock.patch.object(player, "active", return_value=True):
            with mock.patch.object(player.time, "time", side_effect=itertools.count(0, 1)):
                player.confirm(player.OBS, 3)


if __name__ == "__main__":
    unittest.main()
