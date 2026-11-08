# Cutting to music: the craft

## Beats, bars and why cuts land on them

A **beat** is the pulse you tap your foot to; most pop and folk music groups beats in fours (a
**bar**), and the first beat of a bar (the **downbeat**) is the strongest. A cut that lands on a
beat feels intentional; a cut a few frames off feels sloppy even when nobody can say why. Cutting
on every beat is frantic: hold shots for 4-8 beats (2-3.5 s at 120 BPM) and save the fast cutting
for the teaser or a peak.

- **Payoff on the downbeat.** The splash, the jump, the laugh should land on or just after a strong
  beat. Move the shot's in-point so the action sits there (`in_s` of the cut).
- **Change shots on the phrase.** Music changes every 4 or 8 bars; a new chapter, a new place, a
  new mood should begin where the music changes, ideally on the first shot of that chapter.
- **Slow songs, longer shots.** At 70 BPM a 4-beat shot is 3.4 s; at 140 BPM it is 1.7 s. Let the
  tempo set the pace rather than forcing one shot length.

## Placing a cue

1. **Entry**: start where the band, the beat or the riff arrives. A 15 s ambient intro under the
   first shots of a teaser kills it. `analyze.py` lists `entries` (level jumps of 8 dB or more);
   `--profile START END 0.25` shows the exact moment.
2. **Hit aimed at a shot**: find the hit (a drum fill ending, a full-band downbeat, the last chord)
   in the profile, then `in_s = hit_time - (length of the cuts before that shot)`. Cut lengths snap
   to beats, so check the cut list after the walk and adjust by a beat.
3. **Natural ending**: `end_at` = the second where the track has rung out (`ends_at`). The walk
   chooses `in_s` so the song's real ending lands on the held last shot. A fade-out over a song
   that is still going sounds like the editor ran out of time.
4. **Final chord by harmony, not loudness.** A loud piece has no level jump at its last chord; the
   profile's end, or listening, finds it.

## Transitions between cues

- Default: the outgoing cue fades over ~1.2 s while the next starts on the first shot of the new
  chapter (0.3 s overlap, `tail`).
- **Smash cut**: a gentle song stops dead (`fade_out` 0.25, `tail` 0.05) and a big one starts on
  the first frame of the action, no fade-in. Use it once, for the biggest moment.
- When the incoming song starts quietly, give the outgoing one a longer tail (`tail` 1.0,
  `fade_out` 2.0) so there is no hole at the join.

## J-cuts and L-cuts with the clips' own sound

A **J-cut** lets you hear the next shot before you see it (the audio edit comes first, so the two
tracks look like a J on a timeline): the waves start a half-second before the beach appears, and
the cut feels motivated. An **L-cut** is the reverse: the sound of a shot carries on over the next
picture (a laugh rolling into the following shot). In picks.json: `"j": 0.5` or `"l": 0.5` on a
cut; the clips' own sound (the bed) is mixed low under the music, so these are gentle.
In DaVinci Resolve: select the audio edit point and trim it alone with the Trim tool (T), or
unlink the clip's audio (Ctrl/Cmd+Shift+L toggles linked selection) and drag its edge.

## Levels

- The music should carry the montage without burying the clips: cues ~-20 LUFS over the clips'
  own sound at ~-21 dB RMS, the whole mix normalised to -16 LUFS (a comfortable level for phones,
  laptops and TVs; YouTube turns louder uploads down to about -14 LUFS and leaves quieter ones alone).
- Wind, chatter, traffic: lower (`bed_db` -6), not muted. Silence under music sounds fake.
- A spoken line worth hearing: a featured `moment` with `duck: true, speech: true`; the music dips
  ~6 dB under it.
