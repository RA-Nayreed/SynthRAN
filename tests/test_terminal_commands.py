from __future__ import annotations

import unittest

from synthran.terminal import (
    COMMANDS,
    TerminalCommandError,
    command_allowed,
    parse_command,
    render_help,
    require_command_allowed,
)


class TerminalCommandTests(unittest.TestCase):
    def test_registry_contains_the_operator_command_contract_once(self) -> None:
        names = [item.name for item in COMMANDS]
        self.assertEqual(
            names,
            [
                "/status",
                "/inspect",
                "/reserve",
                "/up",
                "/verify",
                "/recover",
                "/down",
                "/run",
                "/stop",
                "/collect",
                "/logs",
                "/config",
                "/mode",
                "/help",
                "/clear",
                "/quit",
            ],
        )
        self.assertEqual(len(names), len(set(names)))

    def test_plain_language_is_not_interpreted_as_lifecycle_control(self) -> None:
        for value in (
            "status",
            "please deploy the network",
            "bring everything up",
            "reserve sopnode-f2",
        ):
            with self.assertRaises(TerminalCommandError):
                parse_command(value)

    def test_commands_without_arguments_reject_inline_resource_overrides(self) -> None:
        self.assertEqual(parse_command("/status").name, "/status")
        self.assertEqual(parse_command(" /verify ").name, "/verify")
        for value in (
            "/reserve sopnode-f2",
            "/up --core-node sopnode-f1",
            "/down all",
            "/verify 12.1.1.2",
        ):
            with self.assertRaises(TerminalCommandError):
                parse_command(value)

    def test_fixed_subcommands_are_required_and_exact(self) -> None:
        cases = {
            "/inspect resources": ("/inspect", "resources"),
            "/inspect network": ("/inspect", "network"),
            "/run baseline": ("/run", "baseline"),
            "/run congestion": ("/run", "congestion"),
            "/logs open5gs": ("/logs", "open5gs"),
            "/config experiment": ("/config", "experiment"),
            "/mode operate": ("/mode", "operate"),
        }
        for value, expected in cases.items():
            request = parse_command(value)
            self.assertEqual((request.name, request.subcommand), expected)

        for value in (
            "/inspect",
            "/run",
            "/run arbitrary",
            "/logs core",
            "/mode admin",
            "/config experiment extra",
        ):
            with self.assertRaises(TerminalCommandError):
                parse_command(value)

    def test_observe_mode_blocks_every_mutating_command(self) -> None:
        mutating = [item for item in COMMANDS if item.mutates]
        self.assertTrue(mutating)
        for item in mutating:
            text = item.name
            if item.subcommands:
                text += " " + item.subcommands[0]
            request = parse_command(text)
            self.assertFalse(command_allowed(request, "observe"))
            with self.assertRaises(TerminalCommandError):
                require_command_allowed(request, "observe")
            self.assertTrue(command_allowed(request, "operate"))

    def test_read_only_commands_are_available_in_both_modes(self) -> None:
        for value in (
            "/status",
            "/inspect network",
            "/verify",
            "/collect",
            "/logs ue",
            "/config resources",
            "/help",
            "/clear",
            "/quit",
            "/mode operate",
        ):
            request = parse_command(value)
            self.assertTrue(command_allowed(request, "observe"))
            self.assertTrue(command_allowed(request, "operate"))

    def test_destructive_teardown_is_explicit_r3(self) -> None:
        request = parse_command("/down")
        self.assertTrue(request.spec.mutates)
        self.assertEqual(request.spec.risk, "R3")

    def test_command_risk_and_mutation_flags_are_consistent(self) -> None:
        for item in COMMANDS:
            if item.mutates:
                self.assertIn(item.risk, {"R2", "R3"})
            else:
                self.assertIn(item.risk, {"R0", "R1"})

    def test_help_is_registry_derived_and_contains_no_hidden_commands(self) -> None:
        help_lines = render_help()
        self.assertEqual(len(help_lines), len(COMMANDS))
        for item, line in zip(COMMANDS, help_lines):
            self.assertTrue(line.startswith(item.name))
            self.assertIn(f"[{item.risk}]", line)

    def test_unknown_command_and_malformed_quoting_fail_closed(self) -> None:
        with self.assertRaises(TerminalCommandError):
            parse_command("/shell")
        with self.assertRaises(TerminalCommandError):
            parse_command('/status "unterminated')
        with self.assertRaises(TerminalCommandError):
            parse_command("")


if __name__ == "__main__":
    unittest.main()
