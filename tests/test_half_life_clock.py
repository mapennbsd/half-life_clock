"""CLI regression tests; fake ALSA commands never touch audio hardware."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "half-life_clock.py"


class ClockCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="half-life-clock-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin_directory = self.directory / "bin"
        self.bin_directory.mkdir()
        self.log = self.directory / "commands.jsonl"
        stub = (
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "name = Path(sys.argv[0]).name\n"
            "with open(os.environ['HLCLOCK_TEST_LOG'], 'a') as log:\n"
            "    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
            "sys.exit(int(os.environ['HLCLOCK_TEST_' + name.upper()]))\n"
        )
        for name in ("amixer", "aplay"):
            executable = self.bin_directory / name
            executable.write_text(stub)
            executable.chmod(0o700)

    def run_clock(self, *arguments, mixer_status=0, player_status=0):
        if self.log.exists():
            self.log.unlink()
        environment = os.environ.copy()
        environment.update(
            PATH=str(self.bin_directory),
            HLCLOCK_TEST_LOG=str(self.log),
            HLCLOCK_TEST_AMIXER=str(mixer_status),
            HLCLOCK_TEST_APLAY=str(player_status),
        )
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commands = (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists() else []
        )
        return result, commands

    def test_command_failure_exits_nonzero_and_stops(self):
        for command, mixer_status, player_status, expected_commands in (
            ("amixer", 9, 0, ["amixer"]),
            ("aplay", 0, 9, ["amixer", "aplay"]),
        ):
            with self.subTest(command=command):
                result, commands = self.run_clock(
                    mixer_status=mixer_status, player_status=player_status
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual([entry[0] for entry in commands], expected_commands)
                self.assertIn(command, result.stderr)
                self.assertIn("9", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_out_of_range_volume_is_rejected_before_commands_run(self):
        for volume in ("-1", "101", "200"):
            with self.subTest(volume=volume):
                result, commands = self.run_clock("--volume", volume)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(commands, [])
                self.assertIn("0", result.stderr)
                self.assertIn("100", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_successful_default_and_valid_volumes(self):
        for arguments, expected_volume in (
            ((), "50%"),
            (("--volume", "0"), "0%"),
            (("--volume", "100"), "100%"),
            (("-v", "80"), "80%"),
        ):
            with self.subTest(arguments=arguments):
                result, commands = self.run_clock(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(len(commands), 2)
                self.assertEqual(
                    commands[0], ["amixer", "-q", "-M", "sset", "PCM", expected_volume]
                )
                self.assertEqual(commands[1][:2], ["aplay", "wavs/time_is.wav"])
                for filename in commands[1][1:]:
                    self.assertTrue((ROOT / filename).is_file(), filename)

    def test_noninteger_volume_is_rejected_before_commands_run(self):
        for volume in ("loud", "50.5"):
            with self.subTest(volume=volume):
                result, commands = self.run_clock("--volume", volume)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(commands, [])
                self.assertIn("invalid int value", result.stderr)

    def test_help_does_not_run_audio_commands(self):
        result, commands = self.run_clock("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, [])
        self.assertIn("--volume", result.stdout)

    def test_unavailable_commands_have_clean_errors(self):
        for command, expected_commands in (
            ("amixer", []),
            ("aplay", ["amixer"]),
        ):
            for failure in ("missing", "not_executable"):
                with self.subTest(command=command, failure=failure):
                    executable = self.bin_directory / command
                    disabled = executable.with_suffix(".disabled")
                    if failure == "missing":
                        executable.rename(disabled)
                    else:
                        executable.chmod(0o600)
                    try:
                        result, commands = self.run_clock()
                    finally:
                        if failure == "missing":
                            disabled.rename(executable)
                        else:
                            executable.chmod(0o700)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual([entry[0] for entry in commands], expected_commands)
                    self.assertIn(command, result.stderr)
                    self.assertIn("Could not run", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
