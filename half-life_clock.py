#!/usr/bin/env python3
#
## Calomel.org Half-Life 1 (1998 series) talking clock
## Python port of half-life_clock.pl
#

import argparse
import bisect
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave
from array import array
from datetime import datetime

## the clips live beside the script, wherever it is deployed
BASE = Path(__file__).resolve().parent / "wavs"
DEFAULT_VOLUME = 50   # matches hlclock.sh
## a full announcement takes a few seconds; a hung aplay (the ALSA meter
## plugin deadlocked on 2026-10-14) held the only playback device for days
DEFAULT_TIMEOUT = 60

## Speaker pHAT VU meter: the SN3218 LED driver on I2C, lit the way
## pivumeter's speaker-phat output did, but from the clips themselves rather
## than an ALSA meter plugin in the audio path (where pivumeter deadlocked)
LED_BUS = 1
LED_ADDRESS = 0x54
LED_CHANNELS = (0, 1, 2, 4, 6, 8, 10, 12, 14, 16)  # the 10 LEDs of 18 outputs
LED_BRIGHTNESS = 128      # pivumeter's brightness
LED_FULL_SCALE = 15000    # a 16-bit peak this high lights the whole bar
LED_DECAY = 0.5           # pivumeter's decay_ms: each update the bar falls
                          # by (update time / decay) of its height
LED_FRAME = 1 / 30        # seconds between updates
## pivumeter metered after the softvol PCM control, so the bar grew with the
## volume.  The control spans -51 dB to 0 dB in 0.2 dB steps, and on it
## amixer -M is linear in dB (measured on moron 2026-10-25: 50% = -25.4 dB).
## The bar takes half of that attenuation: the full amount, as pivumeter
## did, left it nearly dark at the usual 30-60%.
SOFTVOL_MIN_DB = -51.0
LED_VOLUME_SHARE = 0.5
## aplay's own delays, which the LEDs wait out (timed on moron, a Pi Zero W,
## 2026-10-25, on silent copies of the clips): about 80 ms from launch to
## sound, and about 75 ms between files, while it drains and reopens the
## device.  Without them the bar ran a quarter second ahead by "AM".
LED_START_DELAY = 0.080
LED_FILE_GAP = 0.075


def warn(message):
    print(f"half-life_clock: {message}", file=sys.stderr)


def volume_gain(percent):
    """The bar's gain at an amixer -M percentage: half softvol's, in dB."""
    if percent <= 0:
        return 0.0                              # softvol's lowest step mutes
    return 10 ** (LED_VOLUME_SHARE * SOFTVOL_MIN_DB * (1 - percent / 100) / 20)


def clip_levels(paths, gain=1.0, frame=LED_FRAME,
                start=LED_START_DELAY, gap=LED_FILE_GAP):
    """(start second, 16-bit peak after gain) per frame of the clips as aplay
    plays them: in series, after its start delay and gaps between files."""
    timeline, offset = [(0.0, 0)], start
    for path in paths:
        with wave.open(str(path)) as clip:
            width, rate = clip.getsampwidth(), clip.getframerate()
            channels, frames = clip.getnchannels(), clip.getnframes()
            data = clip.readframes(frames)
        if width == 1:          # unsigned 8-bit, centred on 128
            samples, centre, scale = data, 128, 256
        elif width == 2:        # signed 16-bit little-endian
            samples, centre, scale = array("h", data), 0, 1
            if sys.byteorder == "big":
                samples.byteswap()
        else:
            raise ValueError(f"{path}: {8 * width}-bit audio")
        step = max(1, round(rate * frame))
        for first in range(0, frames, step):
            chunk = samples[first * channels:(first + step) * channels]
            peak = max(max(chunk) - centre, centre - min(chunk)) * scale
            timeline.append((offset + first / rate, peak * gain))
        offset += frames / rate
        timeline.append((offset, 0))            # dark through the gap
        offset += gap
    return timeline


class VuMeter:
    """The pHAT's 10-LED bar, as pivumeter's speaker-phat.c drove it."""

    def __init__(self):
        try:
            import smbus
        except ImportError:
            import smbus2 as smbus
        self.bus = smbus.SMBus(LED_BUS)
        self.write(0x00, [0x01])                # leave shutdown
        self.write(0x13, [0xFF, 0xFF, 0xFF])    # enable all 18 outputs
        self.show(0)

    def write(self, register, values):
        self.bus.write_i2c_block_data(LED_ADDRESS, register, values)

    def show(self, level):
        bar = level / LED_FULL_SCALE * LED_BRIGHTNESS * 10
        pwm = [0] * 18
        for led, channel in enumerate(LED_CHANNELS):
            pwm[channel] = int(max(0, min(LED_BRIGHTNESS, bar - led * LED_BRIGHTNESS)))
        self.write(0x01, pwm)
        self.write(0x16, [0x01])                # latch the new values

    def run(self, timeline, stop):
        """Follow the timeline from now until stop is set, then go dark."""
        times = [start for start, _ in timeline]
        level, keep = 0.0, 1 - LED_FRAME / LED_DECAY
        began = time.monotonic()
        try:
            while not stop.wait(LED_FRAME):
                index = bisect.bisect_right(times, time.monotonic() - began) - 1
                peak = timeline[index][1] if index >= 0 else 0
                level = max(peak, level * keep)
                self.show(level)
        except Exception as error:
            warn(f"VU LEDs stopped: {error}")
        finally:
            try:
                self.show(0)
            except Exception:
                pass


def start_leds(paths, volume):
    """Light the VU LEDs for these clips; on any failure, warn and play on."""
    try:
        timeline = clip_levels(paths, volume_gain(volume))
        meter = VuMeter()
    except Exception as error:
        warn(f"VU LEDs off: {error}")
        return None
    stop = threading.Event()
    thread = threading.Thread(target=meter.run, args=(timeline, stop), daemon=True)
    thread.start()
    return stop, thread


def stop_leds(leds):
    if leds:
        stop, thread = leds
        stop.set()
        thread.join(timeout=2)


def run_audio_command(command, timeout, leds=None):
    """Stop with a useful diagnostic if an ALSA command fails or hangs."""
    try:
        process = subprocess.Popen(command)
    except OSError as error:
        stop_leds(leds)
        raise SystemExit(f"Could not run {command[0]}: {error}") from None
    try:
        status = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        ## SIGKILL: a deadlocked aplay ignores SIGTERM, since its handler
        ## deadlocks closing the device
        process.kill()
        process.wait()
        raise SystemExit(
            f"{command[0]} timed out after {timeout} seconds and was killed"
        ) from None
    finally:
        stop_leds(leds)
    if status != 0:
        raise SystemExit(f"{command[0]} failed (exit status {status})")


parser = argparse.ArgumentParser(description="Half-Life 1 talking clock")
parser.add_argument(
    "-v", "--volume", type=int, default=DEFAULT_VOLUME,
    help=f"PCM volume percent, 0–100 (default: {DEFAULT_VOLUME}). "
         f"Use 80 for the old hlclock_high.sh behavior."
)
parser.add_argument(
    "--timeout", type=int, default=DEFAULT_TIMEOUT,
    help=f"seconds before a hung amixer or aplay is killed "
         f"(default: {DEFAULT_TIMEOUT})"
)
parser.add_argument(
    "--no-leds", action="store_true",
    help="play without driving the Speaker pHAT's VU LEDs"
)
args = parser.parse_args()
if not 0 <= args.volume <= 100:
    parser.error("--volume must be between 0 and 100 (inclusive)")
if args.timeout < 1:
    parser.error("--timeout must be at least 1")

## set PCM volume (was amixer -q -M sset PCM NN% in hlclock*.sh)
run_audio_command(["amixer", "-q", "-M", "sset", "PCM", f"{args.volume}%"],
                  args.timeout)

## collect the system time
## 12 hour time
now = datetime.now()
hour = now.strftime("%I")   # zero-padded, e.g. "01".."12"
## 24 hour time
# hour = now.strftime("%H")

minute = int(now.strftime("%M"))
ampm = now.strftime("%p")   # "AM" / "PM"

audio = []

## "the time is" wav
audio.append(f"{BASE}/time_is.wav")

## the hour time wav
audio.append(f"{BASE}/{hour}.wav")

## the minute wav. check for minutes which are less than 20
## so numbers in the teens and 1-9 play
if minute > 20:
    min1 = minute - (minute % 10)
    min2 = minute % 10
    audio.append(f"{BASE}/{min1}.wav")
    if min2 != 0:
        audio.append(f"{BASE}/{min2}.wav")
else:
    if minute != 0:
        audio.append(f"{BASE}/{minute}.wav")

## add AM or PM to the time stamp
if ampm:
    audio.append(f"{BASE}/{ampm}.wav")

## Speak the time in series to avoid pauses between files, with the VU
## LEDs following the clips at this volume; the LEDs start just before
## aplay, close enough for speech
leds = None if args.no_leds else start_leds(audio, args.volume)
run_audio_command(["aplay"] + audio, args.timeout, leds)
