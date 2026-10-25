"""CLI regression tests; fake ALSA commands and a fake smbus module never
touch audio or LED hardware."""

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
            "import time\n"
            "time.sleep(float(os.environ.get('HLCLOCK_TEST_' + name.upper() + '_SLEEP', '0')))\n"
            "sys.exit(int(os.environ['HLCLOCK_TEST_' + name.upper()]))\n"
        )
        for name in ("amixer", "aplay"):
            executable = self.bin_directory / name
            executable.write_text(stub)
            executable.chmod(0o700)
        ## found before any real smbus through PYTHONPATH; logs each write
        self.python_directory = self.directory / "python"
        self.python_directory.mkdir()
        (self.python_directory / "smbus.py").write_text(
            "import json, os\n"
            "def log(*entry):\n"
            "    with open(os.environ['HLCLOCK_TEST_LOG'], 'a') as log:\n"
            "        log.write(json.dumps(['smbus', *entry]) + '\\n')\n"
            "class SMBus:\n"
            "    def __init__(self, bus):\n"
            "        if os.environ.get('HLCLOCK_TEST_SMBUS') == 'fail':\n"
            "            raise OSError(121, 'Remote I/O error')\n"
            "        log('open', bus)\n"
            "    def write_i2c_block_data(self, address, register, values):\n"
            "        log('write', address, register, list(values))\n"
        )

    def run_clock(self, *arguments, mixer_status=0, player_status=0, player_sleep=0,
                  smbus="ok"):
        if self.log.exists():
            self.log.unlink()
        environment = os.environ.copy()
        environment.update(
            PATH=str(self.bin_directory),
            HLCLOCK_TEST_LOG=str(self.log),
            HLCLOCK_TEST_AMIXER=str(mixer_status),
            HLCLOCK_TEST_APLAY=str(player_status),
            HLCLOCK_TEST_APLAY_SLEEP=str(player_sleep),
            HLCLOCK_TEST_SMBUS=smbus,
            PYTHONPATH=str(self.python_directory),
        )
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        entries = (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists() else []
        )
        self.led_writes = [entry[1:] for entry in entries if entry[0] == "smbus"]
        commands = [entry for entry in entries if entry[0] != "smbus"]
        return result, commands

    def assert_leds_dark_at_end(self):
        self.assertEqual(
            self.led_writes[-2:],
            [["write", 0x54, 0x01, [0] * 18], ["write", 0x54, 0x16, [1]]],
        )

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
                self.assertEqual(
                    commands[1][:2], ["aplay", str(ROOT / "wavs" / "time_is.wav")]
                )
                for filename in commands[1][1:]:
                    self.assertTrue(Path(filename).is_file(), filename)

    def test_hung_player_is_killed_after_timeout(self):
        result, commands = self.run_clock("--timeout", "1", player_sleep=30)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([entry[0] for entry in commands], ["amixer", "aplay"])
        self.assertIn("aplay timed out after 1 seconds", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assert_leds_dark_at_end()

    def test_leds_follow_playback_and_go_dark(self):
        result, commands = self.run_clock(player_sleep=0.5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.led_writes[0], ["open", 1])
        self.assertEqual(self.led_writes[1], ["write", 0x54, 0x00, [1]])
        self.assertEqual(self.led_writes[2], ["write", 0x54, 0x13, [0xFF] * 3])
        frames = [w[3] for w in self.led_writes if w[:3] == ["write", 0x54, 0x01]]
        self.assertTrue(any(any(frame) for frame in frames), "no LED lit")
        for frame in frames:
            self.assertEqual(len(frame), 18)
            self.assertTrue(all(0 <= value <= 128 for value in frame), frame)
            ## only the 10 wired outputs are ever lit
            for channel in (3, 5, 7, 9, 11, 13, 15, 17):
                self.assertEqual(frame[channel], 0, frame)
        self.assert_leds_dark_at_end()

    def test_bar_grows_with_volume(self):
        lit = {}
        for volume in ("30", "100", "0"):
            result, commands = self.run_clock("--volume", volume, player_sleep=0.5)
            self.assertEqual(result.returncode, 0, result.stderr)
            frames = [w[3] for w in self.led_writes if w[:3] == ["write", 0x54, 0x01]]
            lit[volume] = max(sum(frame) for frame in frames)
        self.assertGreater(lit["100"], lit["30"])
        self.assertEqual(lit["0"], 0)

    def test_led_failure_still_plays(self):
        result, commands = self.run_clock(smbus="fail")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([entry[0] for entry in commands], ["amixer", "aplay"])
        self.assertIn("VU LEDs off", result.stderr)
        self.assertIn("Remote I/O error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_leds_flag_leaves_the_bus_alone(self):
        result, commands = self.run_clock("--no-leds", player_sleep=0.2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([entry[0] for entry in commands], ["amixer", "aplay"])
        self.assertEqual(self.led_writes, [])

    def test_timeout_below_one_is_rejected_before_commands_run(self):
        result, commands = self.run_clock("--timeout", "0")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(commands, [])

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
