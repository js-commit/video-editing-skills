# Talking-head editing fundamentals

A talking-head video is a person speaking to camera (reviews, tutorials,
explainers). The edit is mostly about the words: what to cut, how to keep the
viewer watching, and what to show over the talking.

## Vocabulary

- **A-roll**: the main footage: the speaker on camera. The story lives in
  its audio.
- **B-roll**: everything laid over the a-roll to show what is being talked
  about (close-ups, screen recordings, product shots, location shots). It
  sits on a track above the a-roll; the speaker's audio keeps playing.
- **Cut**: the point where one clip ends and the next begins.
- **Jump cut**: a cut inside one continuous shot, so the speaker "jumps".
  Standard on YouTube; it removes ums, retakes and dead air.
- **Punch-in**: scaling the a-roll up (110-130%) after a jump cut so the cut
  feels deliberate. Shooting 4K for a 1080p timeline, or 6K/4K for 4K, leaves
  room to punch in without losing sharpness.
- **J-cut**: the next clip's audio starts before its picture (the sound
  leads, shaped like a J on the timeline). **L-cut**: the picture changes but
  the previous audio carries on (the sound trails). Both make cuts feel
  smooth; use them when switching between a-roll and b-roll or between
  speakers.
- **Pacing**: how fast information arrives. Too slow = viewers leave; too
  fast = they can't follow.
- **Hook**: the first 5-30 seconds, which decide whether people stay.
- **Retention**: the share of viewers still watching at each moment
  (YouTube Studio > Analytics > a video > Engagement shows the graph).

## The cutting pass (the first cut)

1. Watch or read through once (a transcript helps; the aroll-draft skill
   does this pass automatically and gives you a first cut to refine).
2. Remove false starts and retakes: keep the **last** good take of a
   sentence, usually the most fluent.
3. Remove ums, long pauses and repeated points. Keep a short breath
   (about 0.1-0.3 s) between sentences so it doesn't sound robotic.
4. Cut on a natural boundary: between words, ideally where the waveform is
   quiet. Cutting mid-word clicks or chops a syllable.
5. Watch it back at normal speed. Your ear catches what your eye misses.

In DaVinci Resolve (Edit page): park the playhead and press ⌘B (Ctrl+B) to
cut, select the bad piece and press ⇧⌫ (Shift+Backspace) to ripple delete
(close the gap). Faster: put the playhead at the start of the bad bit and
press ⌘⇧[ (Ripple Start to Playhead) or at its end ⌘⇧] (Ripple End to
Playhead) to trim and close the gap in one step (in recent versions; the
Trim menu shows the current key).

## Pacing

- Cut anything the viewer already knows or doesn't need.
- Vary rhythm: a short punchy line after a long explanation.
- Change something on screen every few seconds in fast formats (a punch-in,
  b-roll, a graphic). Slower, calmer formats can hold a shot much longer;
  match the energy of the content.
- Don't cut the laugh or the reaction: a beat of silence after a joke or a
  reveal lets it land.

## Hooks

- Start with the payoff or the question, not "Hey guys, welcome back".
- Show the most interesting visual in the first seconds.
- Promise what they'll get, then deliver it soon. Don't over-promise.
- Move intros, channel plugs and sponsor reads after the hook.

## Keeping people watching (retention)

- Open loops: tell them something is coming ("the third one surprised me").
- Remove the slow parts the retention graph shows as dips. A sharp drop at
  the start means the hook did not match the title or thumbnail.
- B-roll and graphics to illustrate, not decorate: show the thing being
  said, at the moment it is said.
- End when the content ends. A long outro loses viewers before the end
  screen.

## B-roll on top

- Lay b-roll on the track above (V2) so the a-roll keeps playing underneath.
- Start b-roll on the word it illustrates, or a few frames before.
- Hide jump cuts with b-roll when a punch-in would look odd.
- Each b-roll shot: usually 2-6 seconds. Very short flashes read as flicker
  (keep anything longer than about a second unless it's a deliberate
  montage).
- Use J/L-cuts on b-roll with its own sound (ambient sound underneath at low
  level adds life).

## Common beginner mistakes

- Keeping every take "just in case": decide and cut.
- Music too loud under the voice (see audio.md).
- Jump cuts with no change: the head twitches. Punch in or cover with b-roll.
- Exporting at the wrong frame rate or resolution (see resolve-tour.md).
