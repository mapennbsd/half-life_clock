#!/usr/bin/perl

use strict;

#
## Calomel.org Half-Life 1 (1998 series) talking clock
# 

my $base="wavs";

## collect the system time using the date binary (pick one)
 ## 12 hour time 
  my $hour=`date +%I`; chop($hour);
 ## 24 hour time 
 #my $hour=`date +%H`; chop($hour);

my $minute=`date +%M`; chop($minute);
my $APM=`date +%p`; chop($APM);

## "the time is" wav
push(my @audio,"$base/time_is.wav");

## the hour time wav
  push(@audio,"$base/$hour.wav");

## the minute wav. check for minutes which are less then 20
## so numbers in the teens and 1-9 play
if($minute > 20){
  my $min1=eval($minute-($minute%10));
  my $min2=eval($minute%10);
  push(@audio,"$base/$min1.wav");
  unless($min2 == "0"){push(@audio,"$base/$min2.wav");}
} else {
  if ($minute != 0) {
     push(@audio,"$base/$minute.wav");
  }
}

## add AM or PM to the time stamp
if($APM) {
   push(@audio,"$base/$APM.wav");
}

## Speak the time in series to avoid pauses between files
#system(`play -q @audio`);
system(`aplay @audio`);
