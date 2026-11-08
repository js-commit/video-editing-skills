# What makes a Short work

A Short is watched in a feed the viewer is already scrolling. Nobody chose it from
a list; it started playing on its own. So the first second decides everything,
and the rest has to keep earning the next second.

## The four things that matter

1. **The hook (first 2 seconds).** Say the most interesting thing first: a claim,
   a number, a surprising result, the question the short answers. "Here is the one
   setting most people never change" works; "So, as I was saying" loses the viewer.
   The picture in those seconds should be the sharpest, most active shot you have,
   and the caption should be on screen already.
2. **One idea, self-contained.** A Short is not a trailer for the long video; it
   delivers one complete point. A viewer who never saw the long-form must follow
   it: no "as I said earlier", no "this" pointing at something not in the short.
3. **Movement.** On a phone, a talking head cropped to 9:16 is a face filling the
   screen. Change the picture every few seconds: show the thing being talked
   about, punch in, stack the speaker over the subject, cut to b-roll (footage
   that illustrates what is said). The voice carries the story; the picture keeps
   the eyes.
4. **An ending that pays off.** End on the verdict, the result or a question the
   comments can answer. A clean last sentence also makes a loop feel natural
   (Shorts replay automatically).

Length: 15-60 seconds is the sweet spot. Shorts may run up to 3 minutes, but a
tight 25 s short that stays on its point beats a 55 s one padded to "about a minute".

## Words worth knowing

- **9:16 / vertical / portrait**: the phone-screen shape, 1080x1920 pixels (or
  2160x3840 for 4K).
- **Crop**: cutting a 9:16 window out of the 16:9 picture. You choose where the
  window sits (on the speaker, on the product).
- **Fit (blur-pad)**: showing the whole 16:9 picture across the width with a
  blurred, darkened copy filling the space above and below. For screen
  recordings and wide shots that a crop would ruin. Never black bars.
- **Stack**: two pictures, one above the other (the speaker on top, what they
  talk about below).
- **Punch-in**: zooming into part of the picture (2x = half the width).
- **Burned-in captions**: words drawn into the video itself, so they show
  everywhere, even with the sound off (most Shorts are watched muted).
- **LUFS**: a loudness measure. YouTube plays everything at about -14 LUFS; a
  quieter short just sounds weak next to the others.

## The safe zones

The YouTube app draws its own interface over the bottom and right of a Short.
Anything important there is hidden. On a 1080x1920 frame:

```
 +---------------------------+
 |  top ~8 %: search, menu   |   y 0-154
 |                           |
 |   SAFE: subject, faces,   | r |
 |   captions, text          | i |  right ~13 %: like, comment,
 |                           | g |  share, remix buttons (x 940+)
 |                           | h |
 |                           | t |
 +---------------------------+---+
 | bottom ~22 %: title, channel,  |  y 1498-1920
 | description, sound ticker      |
 +-------------------------------+
```

- Keep captions and on-screen text in the **middle band**: by default this skill
  puts them about two-thirds of the way down over a crop (bottom of the text near
  y 1220), lower in a fit shot's blurred band, and just above the seam in a stack.
- Keep faces and the subject out of the bottom fifth and away from the right edge.
- `qc_short.py --sheet` shades these zones red on every frame it samples, and
  measures the caption bounding box against them.

## Framing choices, in order of preference

1. The subject itself (the product, the screen, the place) when the words are
   about it: a b-roll swap from elsewhere in the long-form, the project's footage
   or the b-roll library.
2. The speaker together with the subject (hands-on, over the shoulder), or a stack
   of face over subject.
3. The face alone only where the delivery is the point: the verdict, the joke,
   the reaction. Keep that under about a fifth of the runtime.

When a b-roll swap replaces the speaker's mouth, pick footage with no visible
talking (lip-sync that does not match is worse than no face). Do not reuse the
same shot twice in one short.
