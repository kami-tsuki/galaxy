import itertools
import socket
import unittest
from unittest import mock

from galaxy import pc
from tests.helpers import JobsCase, make_cfg


class MagicPacketTests(unittest.TestCase):
    def test_colon_separated_mac(self):
        packet = pc.magic_packet("aa:bb:cc:dd:ee:ff")
        self.assertEqual(packet, b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16)
        self.assertEqual(len(packet), 102)

    def test_dash_separated_and_uppercase_mac(self):
        self.assertEqual(pc.magic_packet("AA-BB-CC-DD-EE-01"), b"\xff" * 6 + bytes.fromhex("aabbccddee01") * 16)

    def test_invalid_macs_are_rejected(self):
        for mac in ("", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "gg:bb:cc:dd:ee:ff", "aabbccddeeff"):
            with self.assertRaisesRegex(RuntimeError, "MAC"):
                pc.magic_packet(mac)


class SunshineUpTests(unittest.TestCase):
    def test_false_without_host_and_no_connection_attempt(self):
        with mock.patch.object(pc.socket, "create_connection") as connect:
            self.assertFalse(pc.sunshine_up(make_cfg(PC_HOST="")))
        connect.assert_not_called()

    def test_true_when_port_accepts(self):
        with mock.patch.object(pc.socket, "create_connection") as connect:
            self.assertTrue(pc.sunshine_up(make_cfg(SUNSHINE_PORT="1234")))
        self.assertEqual(connect.call_args.args[0], ("192.0.2.10", 1234))

    def test_false_when_connection_fails(self):
        with mock.patch.object(pc.socket, "create_connection", side_effect=OSError):
            self.assertFalse(pc.sunshine_up(make_cfg()))


class OnlineTests(JobsCase):
    def test_online_is_cached_between_calls(self):
        with mock.patch.object(pc, "sunshine_up", return_value=True) as up:
            self.assertTrue(pc.online(make_cfg()))
            self.assertTrue(pc.online(make_cfg()))
        up.assert_called_once()


class WakeTests(unittest.TestCase):
    def test_broadcasts_packet_to_configured_and_global_broadcast_on_ports_7_and_9(self):
        with mock.patch.object(pc.socket, "socket") as factory:
            pc.wake(make_cfg(PC_BROADCAST="192.0.2.255"))
        sock = factory.return_value.__enter__.return_value
        packet = pc.magic_packet("aa:bb:cc:dd:ee:ff")
        sent = {(call.args[0], call.args[1]) for call in sock.sendto.call_args_list}
        self.assertEqual(sent, {(packet, (host, port)) for host in ("192.0.2.255", "255.255.255.255") for port in (7, 9)})
        sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def test_default_broadcast_is_not_sent_twice(self):
        with mock.patch.object(pc.socket, "socket") as factory:
            pc.wake(make_cfg())
        self.assertEqual(factory.return_value.__enter__.return_value.sendto.call_count, 2)

    def test_invalid_mac_raises_before_opening_socket(self):
        with mock.patch.object(pc.socket, "socket") as factory:
            with self.assertRaises(RuntimeError):
                pc.wake(make_cfg(PC_MAC="nope"))
        factory.assert_not_called()


class BootTests(unittest.TestCase):
    def setUp(self):
        wake = mock.patch.object(pc, "wake")
        up = mock.patch.object(pc, "sunshine_up")
        sleep = mock.patch.object(pc.time, "sleep")
        self.wake, self.sunshine_up, self.sleep = wake.start(), up.start(), sleep.start()
        for patcher in (wake, up, sleep):
            self.addCleanup(patcher.stop)

    def test_returns_at_once_when_sunshine_is_up(self):
        self.sunshine_up.return_value = True
        on_wait = mock.Mock()
        pc.boot(make_cfg(), on_wait)
        on_wait.assert_not_called()
        self.wake.assert_not_called()
        self.sleep.assert_not_called()

    def test_wakes_notifies_and_returns_once_pc_comes_up(self):
        self.sunshine_up.side_effect = [False, False, True, True]
        on_wait = mock.Mock()
        pc.boot(make_cfg(BOOT_WAIT="100"), on_wait)
        on_wait.assert_called_once_with()
        self.wake.assert_called_once()
        self.sleep.assert_called_once_with(5)

    def test_raises_after_deadline_and_keeps_waking_until_then(self):
        self.sunshine_up.return_value = False
        with mock.patch.object(pc.time, "time", side_effect=itertools.count(0, 2)):
            with self.assertRaisesRegex(RuntimeError, "did not come up"):
                pc.boot(make_cfg(BOOT_WAIT="5"))
        self.assertEqual(self.wake.call_count, 2)

    def test_zero_wait_raises_without_waking(self):
        self.sunshine_up.return_value = False
        with self.assertRaises(RuntimeError):
            pc.boot(make_cfg(BOOT_WAIT="0"))
        self.wake.assert_not_called()

    def test_default_on_wait_is_a_no_op(self):
        self.sunshine_up.side_effect = [False, False, True, True]
        pc.boot(make_cfg(BOOT_WAIT="100"))


class PowerTests(unittest.TestCase):
    def run_power(self, action="sleep", **result):
        completed = mock.Mock(returncode=0, stderr="")
        completed.configure_mock(**result)
        with mock.patch.object(pc.subprocess, "run", return_value=completed) as run:
            pc.power(make_cfg(PC_SSH="me@pc"), action)
        return run

    def test_rejects_unknown_action_without_running_ssh(self):
        with mock.patch.object(pc.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "unknown power action"):
                pc.power(make_cfg(PC_SSH="me@pc"), "reboot-now")
        run.assert_not_called()

    def test_requires_ssh_target(self):
        with mock.patch.object(pc.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "PC_SSH"):
                pc.power(make_cfg(PC_SSH=""), "sleep")
        run.assert_not_called()

    def test_runs_ssh_with_matching_remote_command(self):
        for action, command in pc.POWER_COMMANDS.items():
            args = self.run_power(action).call_args.args[0]
            self.assertEqual(args[0], "ssh")
            self.assertEqual(args[-2:], ["me@pc", command])
            self.assertIn("BatchMode=yes", args)

    def test_exit_255_becomes_error_with_stderr(self):
        with self.assertRaisesRegex(RuntimeError, "no route to host"):
            self.run_power(returncode=255, stderr=" no route to host\n")

    def test_exit_255_with_empty_stderr_uses_default_message(self):
        with self.assertRaisesRegex(RuntimeError, "not reachable over SSH"):
            self.run_power(returncode=255, stderr="")

    def test_other_nonzero_exit_codes_are_tolerated(self):
        self.run_power("shutdown", returncode=1)


class LocalAddressTests(unittest.TestCase):
    def test_uses_pi_host_when_configured(self):
        self.assertEqual(pc.local_address(make_cfg(PI_HOST="pi.local")), "pi.local")

    def test_falls_back_to_routing_probe(self):
        with mock.patch.object(pc.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.getsockname.return_value = ("10.1.2.3", 5555)
            self.assertEqual(pc.local_address(make_cfg(PI_HOST="")), "10.1.2.3")
        sock.connect.assert_called_once_with(("192.0.2.10", 9))


if __name__ == "__main__":
    unittest.main()
