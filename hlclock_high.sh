#!/bin/sh

#/usr/bin/amixer -q -M sset PCM 40%
/usr/bin/amixer -q -M sset PCM 80%
cd /home/mapenn/hlclock
/home/mapenn/hlclock/half-life_clock.pl
