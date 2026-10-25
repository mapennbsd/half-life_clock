# half-life_clock

Version: **1.2.0** (see `VERSION` and Git tag `v1.2.0`).

A talking clock that announces the current time using voice clips from
Half-Life 1 (1998 series), sourced from [Calomel.org](https://calomel.org/).
Built to run from `cron` on a dedicated Raspberry Pi Zero with a speaker HAT.

## Files

- `half-life_clock.py` — Python port (current version). Reads the system
  time, picks the matching `.wav` clips from `wavs/`, sets PCM volume via
  `amixer`, and plays them back-to-back with `aplay` while lighting the
  Speaker pHAT's VU LEDs to follow them.
- `half-life_clock.pl` — original Perl version.
- `hlclock.sh` / `hlclock_high.sh` — original cron wrapper scripts that set
  PCM volume (50% / 80%) via `amixer` before calling the Perl script. Their
  volume logic is now built into `half-life_clock.py` via `--volume`.
- `wavs/` — the Half-Life voice clips (`time_is.wav`, hour/minute number
  clips, `AM.wav`/`PM.wav`).

## Usage

```sh
# normal volume (50%, the hlclock.sh default)
python3 half-life_clock.py

# louder (matches the old hlclock_high.sh)
python3 half-life_clock.py --volume 80

# any other PCM volume percentage
python3 half-life_clock.py --volume 65
```

The clips are read from the `wavs/` directory beside the script, so it can
run from any working directory.

`--volume` accepts integers from 0 through 100 inclusive. Invalid values
exit with status 2 before any mixer or playback command runs.

`--timeout` (default 60 seconds) kills a hung `amixer` or `aplay` with
SIGKILL and exits with status 1. On 2026-10-14 an `aplay` deadlocked in the
ALSA meter plugin and held the HAT's only playback device for 11 days, so
every later run failed with "Device or resource busy"; a deadlocked `aplay`
ignores SIGTERM.

## VU LEDs

The Pimoroni Speaker pHAT's 10-LED bar (an SN3218 driver at 0x54 on I2C
bus 1) follows the clips: their peak level every 1/30 s, a full bar at a
16-bit peak of 15000, decaying by a fifteenth of its height each update
(pivumeter's 500 ms), brightness 128. These are the values pivumeter's
`speaker-phat` output used. The clock now drives the
LEDs itself, so the ALSA chain needs no meter plugin; the meter plugin is
where aplay deadlocked on 2026-10-14. Like pivumeter, which metered after
the `PCM` softvol control, the bar grows with the volume, but by half as
much: that control runs from -51 dB to 0 dB, linear in dB under `amixer -M`
(50% is -25.4 dB), and the full attenuation left the bar nearly dark at
30-60%. The bar takes half the attenuation in dB (`LED_VOLUME_SHARE`).
The bar also waits out aplay's own delays, timed on the Pi Zero W: about
80 ms from launch to sound and 75 ms between files (`LED_START_DELAY`,
`LED_FILE_GAP`). Retime them on different hardware.

A missing smbus module, I2C bus or LED chip prints `VU LEDs off: ...`, and
the time is still spoken with exit status 0. `--no-leds` skips the LEDs.

If `amixer` fails, playback is skipped rather than using an unknown previous
volume. Failure to run either ALSA command, or a nonzero command exit status,
prints a diagnostic to stderr and exits with status 1. Successful playback
exits with status 0.

## Tests

Run the regression suite from the repo directory:

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary fake `amixer` and `aplay` executables; they do not change
mixer settings or play sound. They cover command failures, missing or
non-executable commands, invalid volume values, valid boundary values, the
default volume, a hung player killed by the timeout, the LED writes during
and after playback, playback when the LEDs fail, and help output. A fake
`smbus` module stands in for the I2C bus. Real audio hardware still needs a separate
smoke test.

## Requirements

- Python 3
- `aplay` and `amixer` (ALSA utils)
- A sound card / mixer with a `PCM` control (as on the target Pi's speaker
  HAT — this control name may differ on other hardware)
- For the VU LEDs: I2C enabled, the `smbus` Python module (`python3-smbus`
  from apt; `smbus2` also works), and the user in the `i2c` group

## Cron example

```
# every hour on the hour, normal volume
0 * * * * python3 /home/pi/half-life_clock/half-life_clock.py

# every half hour during the day, louder
*/30 8-20 * * * python3 /home/pi/half-life_clock/half-life_clock.py --volume 80
```
