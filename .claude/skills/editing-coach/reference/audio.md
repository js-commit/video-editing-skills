# Audio basics

Viewers forgive soft picture; they leave over bad sound. Good audio is mostly
recording well, then a few simple steps in the edit.

## Words

- **dBFS**: decibels below digital full scale. 0 dBFS is the ceiling;
  anything above clips (harsh distortion that can't be undone).
- **Peak**: the loudest instant. **True peak (dBTP)** also counts peaks
  between samples that appear after encoding.
- **LUFS**: loudness as people hear it, averaged over time ("integrated").
  This is what streaming platforms measure.
- **Gain**: how much a clip is turned up or down.
- **Room tone**: the quiet sound of the room with nobody talking. Record
  10-20 seconds of it on every shoot; it patches gaps.
- **Ducking**: lowering music automatically while someone speaks.

## Levels that work

- Record with peaks around -12 to -6 dBFS: loud enough to be clean, with
  headroom for a laugh or a shout. 32-bit float recorders forgive mistakes,
  but still aim for this.
- In the mix, dialogue usually sits around -20 to -10 dBFS on the meters
  with peaks under about -6; music under speech roughly 15-25 dB lower than
  the voice (it should feel like it is "behind" the voice). Sound effects to
  taste.
- Final loudness for YouTube: about **-14 LUFS integrated**, true peaks no
  higher than **-1 dBTP**. YouTube turns louder uploads down to about that
  level (and doesn't turn quiet ones up much), so mastering louder gains
  nothing and too quiet sounds weak next to other videos.
- Measure any file: `python3 <skill>/scripts/loudness.py <file>`.

## Noise

Best fix first:
1. Record closer: a lav or a mic just out of frame beats any software.
2. Kill the source: fridge, fan, air conditioning, open window.
3. Soften the room: rugs, curtains, a sofa, blankets reduce echo.
4. In the edit, gentle noise reduction. Heavy settings make voices sound
   watery or robotic: reduce until the noise is less distracting, not gone.

In DaVinci Resolve: Fairlight FX "Noise Reduction" (Studio) on the clip or
track; Studio's **Voice Isolation** (in the Inspector's audio section or on
the track, in recent versions) separates voice from background and is often
enough by itself; start around 50-70%, not 100%. In the free version, keep
the recording clean and use EQ (a high-pass filter around 80 Hz removes
rumble). Outside Resolve: ffmpeg's `afftdn` filter does mild denoising.

## Fairlight page basics

- Each track has a fader, mute (M), solo (S) and a meter. The Mixer panel
  (top right) shows them all.
- **Clip gain**: select a clip and drag the thin line on it up/down, or set
  Volume in the Inspector (Edit page too).
- **Normalize**: right-click clips > Normalize Audio Levels: matches peaks
  or loudness across clips (choose ITU-R BS.1770 and a target for loudness).
- **Loudness meter**: in the meters/monitoring panel at the top of the
  Fairlight page in recent versions (toggle panels with the buttons at the
  top right); play the whole timeline, then read the integrated value.
- **EQ and dynamics**: double-click a track's EQ or Dynamics in the mixer.
  A gentle compressor (ratio 2:1-4:1) evens out a voice.
- **Keyframes**: ⌥-click (Alt-click) on a clip's volume line adds a point;
  drag points to fade music under a section by hand.

## Music ducking

Simple, reliable: put music on its own track, then lower it under speech
with volume keyframes (about -15 to -25 dB under the voice, fading over half
a second).

Automatic: in Fairlight, a compressor on the music track with its sidechain
fed from the dialogue track (Dynamics > Compressor > Listen/sidechain from
the voice bus) pushes the music down whenever the voice is present. Recent
versions also include ducking tools in the Fairlight FX list; check the
version's FX browser rather than assuming a name.

## Delivery checklist

- No clipping anywhere (meters never hit 0).
- Integrated about -14 LUFS, true peak at or below -1 dBTP.
- Music never fights the voice; listen once on phone speakers and once on
  headphones.
- Stereo, 48 kHz, AAC 320 kb/s in the render settings.

## Music rights

Only use music you have the right to use: YouTube's Audio Library, your own
paid licenses, or Creative Commons tracks that allow your use (credit as
required). Copyrighted songs can block or demonetize a video.
