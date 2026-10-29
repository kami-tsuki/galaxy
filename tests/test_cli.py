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
        for command in ("serve", "stop", "status", "wake", "pair", "pin"):
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

    def test_every_command_has_help_text(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                self.parse("--help")
        text = out.getvalue()
        for command in ("serve", "stop", "status", "wake", "pair", "pin", "connect", "tv", "power", "set"):
            line = next((line for line in text.splitlines() if line.strip().startswith(command + " ")), "")
            self.assertGreater(len(line.split(None, 1)[-1]) if line else 0, len(command), command)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()

    def run_command(self, *argv):
        cli.run(cli.build_parser().parse_args(list(argv)), self.cfg)

    def test_serve_starts_api_with_the_config_loader(self):
        with mock.patch.object(cli.api, "serve") as serve:
            self.run_command("serve")
        serve.assert_called_once_with(config.load)

    def test_connect_calls_session_directly_with_options(self):
        with mock.patch.object(cli.session, "connect") as connect:
            self.run_command("connect", "--source", "main", "--audio", "pc", "--app", "Desktop")
        connect.assert_called_once_with(self.cfg, "main", "pc", "Desktop")

    def test_stop_calls_disconnect_directly(self):
        with mock.patch.object(cli.session, "disconnect") as disconnect:
            self.run_command("stop")
        disconnect.assert_called_once_with(self.cfg)

    def test_tv_passes_boolean_state_directly(self):
        with mock.patch.object(cli.tv, "switch") as switch:
            self.run_command("tv", "on")
            self.run_command("tv", "off")
        self.assertEqual(switch.call_args_list, [mock.call(self.cfg, True), mock.call(self.cfg, False)])

    def test_jobs_exclusive_is_not_used(self):
        self.assertFalse(hasattr(cli, "jobs"))

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

    def test_set_saves_prompted_value_without_echoing_it(self):
        out = io.StringIO()
        with mock.patch.object(cli.getpass, "getpass", return_value="hunter2") as prompt:
            with mock.patch.object(config, "save_setting") as save, contextlib.redirect_stdout(out):
                self.run_command("set", "SUNSHINE_PASS")
        prompt.assert_called_once_with("SUNSHINE_PASS: ")
        save.assert_called_once_with("SUNSHINE_PASS", "hunter2")
        self.assertNotIn("hunter2", out.getvalue())
        self.assertIn("saved", out.getvalue())

    def test_set_propagates_storage_errors(self):
        with mock.patch.object(cli.getpass, "getpass", return_value="bad$"):
            with mock.patch.object(config, "save_setting", side_effect=RuntimeError("cannot be stored")):
                with self.assertRaisesRegex(RuntimeError, "cannot be stored"):
                    self.run_command("set", "API_TOKEN")


class PinPairTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.save = mock.patch.object(config, "save_setting").start()
        self.addCleanup(mock.patch.stopall)
        self.fingerprint = mock.patch.object(cli.sunshine, "fingerprint", return_value="ab" * 32).start()
        self.run = mock.patch.object(cli.subprocess, "run").start()

    def run_command(self, *argv, cfg=None):
        cli.run(cli.build_parser().parse_args(list(argv)), cfg or self.cfg)

    def test_pin_stores_the_current_fingerprint(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.run_command("pin")
        self.fingerprint.assert_called_once_with(self.cfg)
        self.save.assert_called_once_with("SUNSHINE_CERT_SHA256", "ab" * 32)
        self.assertIn("pinned", out.getvalue())

    def test_pin_requires_pc_host(self):
        with self.assertRaisesRegex(RuntimeError, "PC_HOST"):
            self.run_command("pin", cfg=make_cfg(PC_HOST=""))
        self.fingerprint.assert_not_called()
        self.save.assert_not_called()

    def test_pin_does_not_store_anything_when_the_fingerprint_fails(self):
        self.fingerprint.side_effect = OSError("unreachable")
        with self.assertRaises(OSError):
            self.run_command("pin")
        self.save.assert_not_called()

    def test_pair_invokes_moonlight_flatpak_for_pc_host_with_check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.run_command("pair")
        argv = self.run.call_args.args[0]
        self.assertEqual(argv[0], "flatpak")
        self.assertEqual(argv[-2:], ["pair", "192.0.2.10"])
        self.assertTrue(self.run.call_args.kwargs["check"])

    def test_pair_pins_the_certificate_after_pairing(self):
        order = mock.Mock()
        order.attach_mock(self.run, "pair")
        order.attach_mock(self.save, "pin")
        with contextlib.redirect_stdout(io.StringIO()):
            self.run_command("pair")
        self.assertEqual([call[0] for call in order.mock_calls], ["pair", "pin"])

    def test_pair_requires_pc_host_before_running_moonlight(self):
        with self.assertRaisesRegex(RuntimeError, "PC_HOST"):
            self.run_command("pair", cfg=make_cfg(PC_HOST=""))
        self.run.assert_not_called()

    def test_failed_pairing_does_not_pin(self):
        self.run.side_effect = subprocess.CalledProcessError(1, "flatpak")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_command("pair")
        self.save.assert_not_called()


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

    def test_invalid_connect_request_exits_with_the_validation_message(self):
        with mock.patch.object(cli.session, "connect", side_effect=ValueError("PC_HOST is not configured")):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["connect"])
        self.assertEqual(caught.exception.code, "galaxy: PC_HOST is not configured")

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
