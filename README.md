# half-life_clock

Version: **1.0.0** — the first numbered version (see `VERSION` and Git tag
`v1.0.0`).

A talking clock that announces the current time using voice clips from
Half-Life 1 (1998 series), sourced from [Calomel.org](https://calomel.org/).
Built to run from `cron` on a dedicated Raspberry Pi Zero with a speaker HAT.

## Files

- `half-life_clock.py` — Python port (current version). Reads the system
  time, picks the matching `.wav` clips from `wavs/`, sets PCM volume via
  `amixer`, and plays them back-to-back with `aplay`.
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

Run from the repo directory (or point `cron` at it with a `cd` first) so the
relative `wavs/` path resolves correctly.

`--volume` accepts integers from 0 through 100 inclusive. Invalid values
exit with status 2 before any mixer or playback command runs.

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
default volume, and help output. Real audio hardware still needs a separate
smoke test.

## Requirements

- Python 3
- `aplay` and `amixer` (ALSA utils)
- A sound card / mixer with a `PCM` control (as on the target Pi's speaker
  HAT — this control name may differ on other hardware)

## Cron example

```
# every hour on the hour, normal volume
0 * * * * cd /home/pi/half-life_clock && python3 half-life_clock.py

# every half hour during the day, louder
*/30 8-20 * * * cd /home/pi/half-life_clock && python3 half-life_clock.py --volume 80
```
