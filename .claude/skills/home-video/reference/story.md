# Montage craft, briefly (teach as it comes up)

## Story structure for a montage

Even a holiday reel has a shape; without one it is a slideshow.

1. **Hook / teaser (first 10-15 s).** The best shots from anywhere in the footage, fast (2.1-2.5 s
   each), best shot first, on an upbeat cue. It promises what is coming. The first 3 seconds decide
   whether people keep watching.
2. **Setup.** Where are we, who is here: the arrival, the first view, faces. Give the viewer their
   bearings before the action.
3. **Chapters.** Days, places or events in the order they happened. Each chapter is a small arc:
   an establishing shot (wide, where), the people (medium, who), details (close, what it felt
   like), the action. A new chapter starts with its first shot, and the music changes there only
   if the mood does.
4. **Climax.** The moment the video builds to (the summit, the first steps, the big jump). Give it
   room: a calmer stretch before it, a musical hit aimed at it, a slightly longer hold, maybe slow
   motion if the clip was shot at 60/120 fps.
5. **Ending.** Wind down: a quiet shot, a wave goodbye, the sunset. The song's own ending lands on
   the last shot; hold it 2-2.7 s; the clips' sound fades with it.

Memorials and life stories run the same way with chapters spanning months or years; they may
breathe a little more (shots up to 4 s) and stay upbeat except for the one stretch that is sad.

## Pacing

- 2-3.5 s per shot is the comfortable montage pace; hold longer only when the action needs it
  (a jump, a wave, a line someone says).
- Vary it: three quick shots then one held shot reads as rhythm; ten 3 s shots read as a metronome.
- Never more than three shots of the same subject in a row; interleave views with people.
- When a video is too long, cut from the last third first: viewers' patience is lowest there.

## Cutting to the beat

The cut list is laid on the song's beats: each shot lasts a whole number of beats, so every cut
lands on one. Put the payoff of a shot on or just after a beat by moving the shot's in-point. Full
craft (in-points, hits, natural endings, transitions): montage-music's `reference/craft.md`.
In DaVinci Resolve you can do the same by hand: play the song, press M on each beat to drop
markers on the timeline, and snap edits to them (N toggles snapping).

## J-cuts and L-cuts

A J-cut brings the next shot's sound in before its picture (the gulls before the harbour); an L-cut
lets a sound run on over the next picture (a laugh carrying across the cut). Both make cuts feel
motivated instead of abrupt. In picks.json: `"j": 0.5` / `"l": 0.5` on a cut (they act on the
clips' own sound, which sits low under the music). In Resolve: unlink the clip's audio
(Ctrl/Cmd+Shift+L toggles linked selection) and drag the audio edit point, or use the Trim tool (T).

## Ambient sound: low, not muted

Silence under music makes a montage feel like a slideshow. Keep every clip's own sound on, low:
wind and chatter turned down (`bed_db` -6), not off; waves, crowds and laughter turned up where they
are the point. Mute only a swear. Duck the music only for a line worth hearing.

## Stabilization tradeoffs

Stabilizing zooms the shot in (8 % by default) to get spare picture to shift. More smoothing needs
more zoom; past ~12 % the crop costs more than the smoothing gives. It cannot fix rolling-shutter
wobble or motion blur, and locking a wobbly shot makes it look warped. Phones already stabilize
most footage, so stabilize only what a person watching calls shaky, judge the result by watching
it move (never by stills), and prefer a calmer stretch of the clip when one exists.
Details: stabilize-clips' SKILL.md.

## Portrait clips in a landscape video

A vertical phone clip on a 16:9 frame gets a blurred, darkened copy of itself behind it
("blur-fill") by default, which reads far better than black bars. Cropping it to fill (`"fit":
"cover"`) keeps only a strip of the middle: fine for a face, bad for a tall view.
