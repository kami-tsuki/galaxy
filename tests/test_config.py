import os
import unittest
from unittest import mock

from galaxy import config
from tests.helpers import TempDirCase, make_cfg


class LoadTests(TempDirCase):
    def test_returns_defaults_when_no_file_and_no_environ(self):
        self.assertEqual(config.load(paths=(self.dir / "missing.env",), environ={}), config.DEFAULTS)

    def test_env_file_overrides_defaults(self):
        path = self.write("a.env", "PC_HOST=10.0.0.1\nBOOT_WAIT=30\n")
        cfg = config.load(paths=(path,), environ={})
        self.assertEqual((cfg["PC_HOST"], cfg["BOOT_WAIT"], cfg["API_PORT"]), ("10.0.0.1", "30", "8787"))

    def test_environ_overrides_env_file(self):
        path = self.write("a.env", "PC_HOST=10.0.0.1\n")
        cfg = config.load(paths=(path,), environ={"PC_HOST": "10.9.9.9"})
        self.assertEqual(cfg["PC_HOST"], "10.9.9.9")

    def test_environ_keys_outside_defaults_are_ignored(self):
        cfg = config.load(paths=(), environ={"PATH": "/bin", "UNRELATED": "1"})
        self.assertNotIn("PATH", cfg)
        self.assertNotIn("UNRELATED", cfg)

    def test_later_file_overrides_earlier_file(self):
        first = self.write("a.env", "PC_HOST=1.1.1.1\nPC_SSH=a\n")
        second = self.write("b.env", "PC_HOST=2.2.2.2\n")
        cfg = config.load(paths=(first, second), environ={})
        self.assertEqual((cfg["PC_HOST"], cfg["PC_SSH"]), ("2.2.2.2", "a"))

    def test_strips_double_and_single_quotes(self):
        path = self.write("a.env", "PC_HOST=\"1.2.3.4\"\nPC_SSH='me@pc'\n")
        cfg = config.load(paths=(path,), environ={})
        self.assertEqual((cfg["PC_HOST"], cfg["PC_SSH"]), ("1.2.3.4", "me@pc"))

    def test_skips_comments_blank_lines_and_lines_without_equals(self):
        path = self.write("a.env", "# PC_HOST=bad\n\n   \nnonsense\n  PC_SSH = x  \n")
        cfg = config.load(paths=(path,), environ={})
        self.assertEqual(cfg["PC_HOST"], "")
        self.assertEqual(cfg["PC_SSH"], "x")

    def test_value_may_contain_equals_sign(self):
        path = self.write("a.env", "API_TOKEN=abc=def==\n")
        self.assertEqual(config.load(paths=(path,), environ={})["API_TOKEN"], "abc=def==")

    def test_load_does_not_mutate_defaults(self):
        path = self.write("a.env", "PC_HOST=1.1.1.1\n")
        config.load(paths=(path,), environ={})
        self.assertEqual(config.DEFAULTS["PC_HOST"], "")


class HelperTests(unittest.TestCase):
    def test_flag_accepts_truthy_spellings_case_insensitively(self):
        for value in ("1", "true", "TRUE", "Yes", " on "):
            self.assertTrue(config.flag({"K": value}, "K"), value)

    def test_flag_rejects_other_values(self):
        for value in ("0", "false", "", "no", "off", "2"):
            self.assertFalse(config.flag({"K": value}, "K"), value)

    def test_pairs_parses_trimmed_items_and_skips_junk(self):
        self.assertEqual(config.pairs("a=1, b = 2,junk,,c=x=y"), {"a": "1", "b": "2", "c": "x=y"})

    def test_pairs_of_empty_text_is_empty(self):
        self.assertEqual(config.pairs(""), {})

    def test_screens_reads_displays(self):
        self.assertEqual(config.screens(make_cfg(DISPLAYS="a=1,b=2")), {"a": "1", "b": "2"})

    def test_screens_ignores_display_named_obs_and_empty_ids(self):
        self.assertEqual(config.screens(make_cfg(DISPLAYS="main=1,obs=2,second=,third=3")), {"main": "1", "third": "3"})

    def test_apps_trims_and_drops_empty_items(self):
        self.assertEqual(config.apps(make_cfg(APPS=" Desktop, ,Steam Big Picture,")), ["Desktop", "Steam Big Picture"])

    def test_obs_enabled_needs_flag_and_password(self):
        self.assertTrue(config.obs_enabled(make_cfg(OBS_ENABLED="true", OBS_PASS="x")))
        self.assertFalse(config.obs_enabled(make_cfg(OBS_ENABLED="true", OBS_PASS="")))
        self.assertFalse(config.obs_enabled(make_cfg(OBS_ENABLED="false", OBS_PASS="x")))

    def test_sources_lists_screens_then_obs_when_enabled(self):
        cfg = make_cfg(DISPLAYS="main=1,second=2", OBS_ENABLED="yes", OBS_PASS="x")
        self.assertEqual(config.sources(cfg), ["main", "second", "obs"])

    def test_sources_omits_obs_without_password(self):
        cfg = make_cfg(DISPLAYS="main=1", OBS_ENABLED="true", OBS_PASS="")
        self.assertEqual(config.sources(cfg), ["main"])

    def test_sources_is_empty_without_displays_or_obs(self):
        self.assertEqual(config.sources(make_cfg(DISPLAYS="")), [])


class SaveSettingTests(TempDirCase):
    def setUp(self):
        super().setUp()
        run_patch = mock.patch.object(config.subprocess, "run")
        self.run = run_patch.start()
        self.addCleanup(run_patch.stop)
        euid_patch = mock.patch.object(os, "geteuid", create=True, return_value=0)
        self.euid = euid_patch.start()
        self.addCleanup(euid_patch.stop)

    def sent(self):
        self.run.assert_called_once()
        return self.run.call_args

    def test_rejects_key_that_is_not_settable(self):
        with self.assertRaisesRegex(RuntimeError, "cannot be set"):
            config.save_setting("PC_HOST", "x", self.dir / "e.env")
        self.run.assert_not_called()

    def test_every_settable_key_is_accepted(self):
        self.assertEqual(set(config.SETTABLE), set(config.SECRETS) | {"SUNSHINE_CERT_SHA256"})
        for key in config.SETTABLE:
            self.run.reset_mock()
            config.save_setting(key, "value", self.dir / "e.env")
            self.run.assert_called_once()

    def test_every_value_rejects_quote_backslash_newline_and_carriage_return(self):
        for key in config.SETTABLE:
            for char in ('"', chr(92), chr(10), chr(13)):
                with self.assertRaisesRegex(RuntimeError, "cannot be stored"):
                    config.save_setting(key, f"a{char}b", self.dir / "e.env")
        self.run.assert_not_called()

    def test_secrets_also_reject_single_quote_dollar_and_hash(self):
        for key in config.SECRETS:
            for char in "'$#":
                with self.assertRaises(RuntimeError):
                    config.save_setting(key, f"a{char}b", self.dir / "e.env")
        self.run.assert_not_called()

    def test_certificate_fingerprint_may_contain_characters_forbidden_in_secrets(self):
        config.save_setting("SUNSHINE_CERT_SHA256", "ab$#'cd", self.dir / "e.env")
        self.assertEqual(self.sent().kwargs["input"], b"SUNSHINE_CERT_SHA256=ab$#'cd\n")

    def test_error_message_lists_the_forbidden_characters(self):
        with self.assertRaises(RuntimeError) as caught:
            config.save_setting("API_TOKEN", "$", self.dir / "e.env")
        self.assertIn("$", str(caught.exception))
        self.assertIn("#", str(caught.exception))

    def test_replaces_existing_key_and_keeps_other_lines(self):
        path = self.write("e.env", "A=1\nSUNSHINE_PASS=old\nAPI_TOKEN_X=keep\nB=2\n")
        config.save_setting("SUNSHINE_PASS", "new", path)
        call = self.sent()
        self.assertEqual(call.args[0], ["tee", str(path)])
        self.assertEqual(call.kwargs["input"], b"A=1\nSUNSHINE_PASS=new\nAPI_TOKEN_X=keep\nB=2\n")
        self.assertTrue(call.kwargs["check"])

    def test_appends_key_when_missing(self):
        path = self.write("e.env", "A=1\n")
        config.save_setting("API_TOKEN", "tok", path)
        self.assertEqual(self.sent().kwargs["input"], b"A=1\nAPI_TOKEN=tok\n")

    def test_creates_content_when_file_does_not_exist(self):
        config.save_setting("OBS_PASS", "p", self.dir / "new.env")
        self.assertEqual(self.sent().kwargs["input"], b"OBS_PASS=p\n")

    def test_uses_plain_sudo_when_not_root(self):
        self.euid.return_value = 1000
        path = self.write("e.env", "")
        config.save_setting("API_TOKEN", "t", path)
        self.assertEqual(self.sent().args[0], ["sudo", "tee", str(path)])

    def test_spaces_and_equals_are_written_verbatim(self):
        path = self.write("e.env", "")
        config.save_setting("SUNSHINE_PASS", "p a=s s", path)
        self.assertEqual(self.sent().kwargs["input"], b"SUNSHINE_PASS=p a=s s\n")

    def test_propagates_tee_failure(self):
        self.run.side_effect = config.subprocess.CalledProcessError(1, "tee")
        with self.assertRaises(config.subprocess.CalledProcessError):
            config.save_setting("API_TOKEN", "t", self.write("e.env", ""))


class ConstantsTests(unittest.TestCase):
    def test_runtime_dir_is_per_user(self):
        with mock.patch.object(os, "getuid", create=True, return_value=1234):
            self.assertEqual(config.runtime_dir(), config.Path("/run/user/1234"))

    def test_new_defaults_exist(self):
        self.assertEqual(config.DEFAULTS["WATCHDOG"], "true")
        self.assertEqual(config.DEFAULTS["SUNSHINE_CERT_SHA256"], "")

    def test_default_token_is_too_short_to_authorize(self):
        self.assertLess(len(config.DEFAULTS["API_TOKEN"]), config.MIN_TOKEN_LENGTH)


if __name__ == "__main__":
    unittest.main()
