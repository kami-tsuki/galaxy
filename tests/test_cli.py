import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from galaxy import cli, config
from tests.helpers import make_cfg


class ParserTests(unittest.TestCase):
    def parse(self, *argv):
        return cli.build_parser().parse_args(list(argv))

    def rejected(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                self.parse(*argv)
        self.assertEqual(caught.exception.code, 2)

    def test_simple_commands(self):
        for command in ("serve", "stop", "status", "wake", "pair"):
            self.assertEqual(self.parse(command).command, command)

    def test_connect_defaults_to_empty_options(self):
        args = self.parse("connect")
        self.assertEqual((args.source, args.audio, args.app), ("", "", ""))

    def test_connect_accepts_options(self):
        args = self.parse("connect", "--source", "second", "--audio", "tv", "--app", "Steam Big Picture")
        self.assertEqual((args.source, args.audio, args.app), ("second", "tv", "Steam Big Picture"))

    def test_tv_power_and_set_arguments(self):
        self.assertEqual(self.parse("tv", "off").state, "off")
        self.assertEqual(self.parse("power", "restart").action, "restart")
        self.assertEqual(self.parse("set", "API_TOKEN").key, "API_TOKEN")

    def test_bad_choices_are_rejected(self):
        self.rejected("connect", "--audio", "loud")
        self.rejected("tv", "toggle")
        self.rejected("power", "reboot")
        self.rejected("set", "PC_HOST")

    def test_missing_or_unknown_command_is_rejected(self):
        self.rejected()
        self.rejected("explode")
        self.rejected("tv")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()

    def run_command(self, *argv):
        cli.run(cli.build_parser().parse_args(list(argv)), self.cfg)

    def test_serve_starts_api(self):
        with mock.patch.object(cli.api, "serve") as serve:
            self.run_command("serve")
        serve.assert_called_once_with(self.cfg)

    def test_connect_runs_exclusively_with_options(self):
        with mock.patch.object(cli.jobs, "exclusive") as exclusive:
            self.run_command("connect", "--source", "main", "--audio", "pc", "--app", "Desktop")
        exclusive.assert_called_once_with(cli.session.connect, self.cfg, "main", "pc", "Desktop")

    def test_stop_runs_disconnect_exclusively(self):
        with mock.patch.object(cli.jobs, "exclusive") as exclusive:
            self.run_command("stop")
        exclusive.assert_called_once_with(cli.session.disconnect, self.cfg)

    def test_tv_passes_boolean_state(self):
        with mock.patch.object(cli.jobs, "exclusive") as exclusive:
            self.run_command("tv", "on")
            self.run_command("tv", "off")
        self.assertEqual([c.args[2] for c in exclusive.call_args_list], [True, False])

    def test_status_prints_json(self):
        out = io.StringIO()
        with mock.patch.object(cli.session, "status", return_value={"phase": "idle"}):
            with contextlib.redirect_stdout(out):
                self.run_command("status")
        self.assertEqual(json.loads(out.getvalue()), {"phase": "idle"})

    def test_wake_and_power(self):
        with mock.patch.object(cli.pc, "wake") as wake, mock.patch.object(cli.pc, "power") as power:
            self.run_command("wake")
            self.run_command("power", "shutdown")
        wake.assert_called_once_with(self.cfg)
        power.assert_called_once_with(self.cfg, "shutdown")

    def test_set_saves_prompted_secret_without_echoing_it(self):
        out = io.StringIO()
        with mock.patch.object(cli.getpass, "getpass", return_value="hunter2") as prompt:
            with mock.patch.object(config, "save_secret") as save, contextlib.redirect_stdout(out):
                self.run_command("set", "SUNSHINE_PASS")
        prompt.assert_called_once_with("SUNSHINE_PASS: ")
        save.assert_called_once_with("SUNSHINE_PASS", "hunter2")
        self.assertEqual(out.getvalue().strip(), "saved")

    def test_pair_invokes_moonlight_flatpak_for_pc_host(self):
        with mock.patch.object(cli.subprocess, "run") as run:
            self.run_command("pair")
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "flatpak")
        self.assertEqual(argv[-2:], ["pair", "192.0.2.10"])


class MainTests(unittest.TestCase):
    def setUp(self):
        load = mock.patch.object(cli.config, "load", return_value=make_cfg())
        self.load = load.start()
        self.addCleanup(load.stop)

    def test_runtime_error_exits_with_prefixed_message(self):
        with mock.patch.object(cli, "run", side_effect=RuntimeError("PC did not come up")):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["wake"])
        self.assertEqual(caught.exception.code, "galaxy: PC did not come up")

    def test_other_expected_errors_also_exit_with_message(self):
        for error in (ValueError("bad"), OSError("io"), subprocess.CalledProcessError(1, "tee")):
            with mock.patch.object(cli, "run", side_effect=error):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(["wake"])
            self.assertTrue(str(caught.exception.code).startswith("galaxy: "))

    def test_busy_error_exits_with_message(self):
        with mock.patch.object(cli.session, "connect"):
            with mock.patch.object(cli.jobs, "exclusive", side_effect=cli.jobs.Busy("another action is running")):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(["connect"])
        self.assertEqual(caught.exception.code, "galaxy: another action is running")

    def test_success_returns_normally_and_runs_command_with_loaded_config(self):
        with mock.patch.object(cli, "run") as run:
            cli.main(["tv", "on"])
        args, cfg = run.call_args.args
        self.assertEqual((args.command, args.state, cfg), ("tv", "on", self.load.return_value))

    def test_unexpected_exceptions_are_not_swallowed(self):
        with mock.patch.object(cli, "run", side_effect=KeyError("x")):
            with self.assertRaises(KeyError):
                cli.main(["wake"])


if __name__ == "__main__":
    unittest.main()
