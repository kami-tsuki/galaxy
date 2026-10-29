import itertools
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from galaxy import player
from tests.helpers import make_cfg


class SessionFileCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "run" / "session.env"


class WriteSessionTests(SessionFileCase):
    def test_round_trips_every_audio_mode(self):
        for mode in player.AUDIO_MODES:
            player.write_session(make_cfg(), "Steam Big Picture", mode, "3840x1080", self.path)
            self.assertEqual(player.read_session(self.path), {"app": "Steam Big Picture", "audio": mode})

    def test_file_content_has_flags_driver_and_resolution(self):
        player.write_session(make_cfg(), "Desktop", "tv", "1920x1080", self.path)
        self.assertEqual(
            self.path.read_text(),
            'SUNSHINE_APP="Desktop"\nAUDIO_FLAGS="--no-audio-on-host"\nAUDIO_DRIVER=alsa\n'
            'RESOLUTION_FLAGS="--resolution 1920x1080"\n',
        )

    def test_creates_missing_parent_directory(self):
        player.write_session(make_cfg(), "Desktop", "both", "1920x1080", self.path)
        self.assertTrue(self.path.is_file())

    def test_default_sunshine_app_is_allowed_even_when_not_in_apps(self):
        cfg = make_cfg(APPS="Other", SUNSHINE_APP="Desktop")
        player.write_session(cfg, "Desktop", "both", "1920x1080", self.path)
        self.assertEqual(player.read_session(self.path)["app"], "Desktop")

    def assert_rejected(self, cfg, app="Desktop", audio="both", resolution="1920x1080", message=""):
        with self.assertRaisesRegex(ValueError, message):
            player.write_session(cfg, app, audio, resolution, self.path)
        self.assertFalse(self.path.exists())

    def test_rejects_unknown_audio_mode(self):
        self.assert_rejected(make_cfg(), audio="surround", message="audio mode")

    def test_rejects_unknown_app(self):
        self.assert_rejected(make_cfg(), app="Calculator", message="unknown app")

    def test_rejects_bad_resolutions(self):
        for resolution in ("", "1920", "1920x", "x1080", "19x10", "123456x1080", "1920x1080 --evil"):
            self.assert_rejected(make_cfg(), resolution=resolution, message="resolution")

    def test_rejects_dangerous_app_names_even_when_configured(self):
        for app in ('A"b', "A\\b", "A$b", "A\nb", "-flag"):
            self.assert_rejected(make_cfg(APPS=f"Desktop,{app}"), app=app, message="invalid app name")


class ReadSessionTests(SessionFileCase):
    def test_missing_file_yields_empty_values(self):
        self.assertEqual(player.read_session(self.path), {"app": "", "audio": ""})

    def test_unrecognised_audio_flags_yield_empty_audio(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('SUNSHINE_APP="X"\nAUDIO_FLAGS="--foo"\nAUDIO_DRIVER=alsa\n')
        self.assertEqual(player.read_session(self.path), {"app": "X", "audio": ""})

    def test_default_path_uses_user_runtime_dir(self):
        with mock.patch.object(os, "getuid", create=True, return_value=1234):
            self.assertEqual(player.session_path(), Path("/run/user/1234/galaxy-session.env"))


class ControlTests(unittest.TestCase):
    def setUp(self):
        run = mock.patch.object(player.subprocess, "run")
        euid = mock.patch.object(os, "geteuid", create=True, return_value=1000)
        self.run, self.euid = run.start(), euid.start()
        self.addCleanup(run.stop)
        self.addCleanup(euid.stop)
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

    def test_start_failure_without_stderr_names_the_unit(self):
        self.run.return_value = mock.Mock(returncode=1, stderr="")
        with self.assertRaisesRegex(RuntimeError, "u.service failed to start"):
            player.control("start", "u.service")

    def test_stop_failure_is_ignored(self):
        self.run.return_value = mock.Mock(returncode=1, stderr="x")
        player.control("stop", "u.service")


class ActiveAndStopAllTests(unittest.TestCase):
    def test_active_reflects_exit_code(self):
        with mock.patch.object(player.subprocess, "run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(player.active("u"))
        with mock.patch.object(player.subprocess, "run", return_value=mock.Mock(returncode=3)):
            self.assertFalse(player.active("u"))

    def test_stop_all_stops_only_active_units(self):
        with mock.patch.object(player, "active", side_effect=lambda unit: unit == player.OBS):
            with mock.patch.object(player, "control") as control:
                player.stop_all()
        control.assert_called_once_with("stop", player.OBS)


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        sleep = mock.patch.object(player.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

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
