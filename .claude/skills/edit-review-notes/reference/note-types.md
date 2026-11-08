# Note types: what a note usually means and what to do

The stamp is where the reviewer paused, usually a second or two after the
moment. The words that matter are usually the sentence that just ended.

## Additive (phase 1, before any cut)

| the note says (examples) | type | action | landing rule |
|---|---|---|---|
| "show a shot of the box here", "b-roll of me using it", "there's footage of this in the other video" | b-roll | search project, library, sibling projects; verify by frames | start on the word start of the sentence; end on the next a-roll cut or layer edge; usually 3-8 s |
| "this shot is too early, use it when I talk about X" | move b-roll | remove it here, lay it at the words about X | split across two mentions if the shot is longer than one slot; each piece >= 1.5 s |
| "show X instead" over existing b-roll | replace | pick the new shot; remove the old one first; keep its edges | the old edges already sit on cuts: reuse them |
| "screenshot of the website / the settings page" | screenshot card | image from the user, enlarged on a blurred copy of itself | over the sentence that names the fact |
| "put the price / the specs / the score on screen", "big text" | text card | transparent PNG or animated overlay with the figures | each figure appears on the word where it is said; never over the face |
| "summarize this in text", "TL;DR card" | text card | short card over the summary sentence | 3 s minimum, longer for more words |
| "zoom in here", "punch in" | punch-in | a scale-up of the a-roll (Resolve: Zoom in the Inspector; ffmpeg: a crop brick) | on a cut or a sentence start, not mid-word |

## Structural (phase 2, latest first)

| the note says (examples) | type | action | landing rule |
|---|---|---|---|
| "I said that twice", "duplicate take", "repeat" | trim a repeat | remove one take, on the silences around it | keep the take the user names, else the one that flows into the next sentence |
| "trim this", "too long", "tighten" | trim | cut the filler or dead air the note is on | never remove a sentence the note did not name; vague notes trim the longest pause and say so |
| "cut this out", "remove this bit" | cut | remove the named span | edges in silence |
| "drop this section", "we don't need the part about X" | delete section | from the first word of the topic to the last before the next | check the result reads as one thought |
| "cut too tight", "put the pause back", "let it breathe" | restore pause | bring back frames from the source gap | listen first: the gap may hold a noise |
| "I'll re-record this", "change the script to say ..." | re-record | cut the old span if asked; marker `RE-RECORD: <note>` | never invent a-roll |
| "add a section about X here" | add section | marker `ADD: <note>`, or insert the named footage if it exists | layers either side still end on their cuts |

## Other

| the note says | action |
|---|---|
| "too loud", "music too loud here", "hum" | audio fix on the a-roll or music level; changes.json kind `audio` / `music` |
| "too dark", "colour is off" | colour note: Resolve, adjust on the Color page or tell the user; ffmpeg, a filter on the take; kind `changed` |
| "is this sharp?", "should we keep this?" | a question: answer it in the report (and changes.json kind `answer`, at the note's moment) |

## Slot rules that apply to every placement

- Read the frames under the slot before laying anything. A person holding
  something up to the lens, or "you can see / look at this" in the words, is
  an on-camera demo: the layer ends before it or starts after it.
- Two notes can share one slot: chain them, one after the other.
- A shot that agrees with the words in general but shows a different
  model or device is a mismatch: cut the piece short before the words that
  name the other thing, or pick another shot.
- A shot that is shorter than the slot: take the whole shot and say so; don't
  loop it or slow it down unless the user asks.
- Never butt two pieces of the same locked-off shot together: it reads as a
  jump cut.
