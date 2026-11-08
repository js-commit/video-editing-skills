---
name: youtube-thumbnails
description: Make YouTube thumbnails from the video's REAL footage - long-form (1280x720) or Shorts (1080x1920) - with the hook taken from the speaker's own words, several distinct concepts (face + subject + question, subject hero, A-vs-B split), bold condensed titles, per-subject labels and clean screen retouches, each under 2 MB; an optional AI-image round when the user has an image tool; a privacy + legibility check; a numbered sheet for the user to pick from, picks filed as thumb-1..3. Works with ffmpeg alone (Pillow optional). Use when asked to "make a thumbnail", "thumbnails for this video", "find a better frame for the thumbnail", "put titles on my frames", "restyle my thumbnails", "AI thumbnail with my face", or to set a thumbnail on YouTube.
argument-hint: "[video-or-project] [short|landscape]"
---

# YouTube thumbnails

Makes thumbnail candidates from frames the footage actually contains, titles them
with the speaker's own verdict, checks them for leaks and legibility, and files the
user's pick as `thumb-1..3`. The deliverable is image files the user picked, not a
suggestion of "a frame that would work".

`$S` below is `${CLAUDE_SKILL_DIR}/scripts`. Run scripts with `python3`.

## Before you start

- **Preferences.** Read `user/preferences.md` (`## general` and `## youtube-thumbnails`).
  They override the defaults here. Map style bullets onto compose flags:
  font -> `--font`, title colour -> `--text-color`, accent colour -> `--accent`,
  "my face on the left" -> text on the other side (`--align right`), text length ->
  how many words you allow. If they say the user is experienced, skip the teaching.
- **Tools.** `python3 $S/thumbkit.py fonts` prints the title font it found, whether
  Pillow is installed and whether ffmpeg has `drawtext`. ffmpeg is required. Pillow
  is optional: without it the ffmpeg engine draws the same layout (slightly harder
  shadows). Never install it unasked; if the user wants it: `python3 -m pip install Pillow`.
- **Font.** Default: the first condensed bold system font found (DIN Condensed,
  Impact, Bebas Neue, Oswald, Arial Narrow, DejaVu Sans Condensed...). The user can
  pin one with `python3 tools/vidkit/settings.py set youtube.thumbnail_font /path/to/font.ttf`
  (or pass `--font` per run). Tell them which font was used (`font` in the output).
- **Where things go.** `python3 $S/thumb_pool.py info <video-or-project>` prints the
  project, the finished video, its format (landscape/short), `dest` (the project's
  finals folder: picks land here as thumb-1..3), the pool folder and the `work`
  folder (sampled frames, composites, references). Never write next to camera originals.

## What makes a thumbnail work (say this briefly to a new user)

A thumbnail is seen at about 200 px wide on a phone, for half a second, next to
a dozen others. So:

- **One idea, one focal point.** A face with a clear emotion, or the subject big and
  sharp. Busy frames turn to mush at feed size.
- **Contrast.** Light subject on a dark background or the reverse; text white or
  yellow with a thick black outline.
- **3-5 words at most, often 1-3.** Big condensed capitals. The thumbnail adds to the
  title, it doesn't repeat it: title "I used it for a month", thumbnail "WORTH IT?".
- **Face emotion.** A real expression that matches the hook (doubt, surprise,
  delight), eyes open, looking at the lens or at the subject.
- **Readable on a phone.** Check the 200 px preview every time. If you can't read it
  in a second there, nobody will.

## Steps

### 1. The hook comes first

Before looking at frames, find the line the speaker would say if a friend asked "so,
should I get it?":

```
python3 $S/hook_lines.py <finished video>          # hooks + "look at this" moments, JSON
python3 $S/hook_lines.py <finished video> --text   # the whole transcript, timestamped
```

It reuses the transcript sidecar (`tools/transcribe.py` makes it if missing; exit 4
means no transcription engine is set up: ask, set it, re-run). Read the whole
transcript, not just the pointers. Cut the verdict to 1-3 words.

- Use the speaker's words or stance, not the easiest statistic.
- A question or a verdict beats a spec: "WORTH IT?", "SKIP IT?", "A DOWNGRADE?".
- **Never claim what the video doesn't say.** "3X FASTER" when the measured figure is
  2.5x is a lie on the cover.

### 2. Find the shots

Check, in order: moments the speaker slated ("look at this", "here it is", the reveal,
the reaction; `moments` from step 1, in the finished video's time), the project's
footage folder, frames the user already saved, then the b-roll library
(`broll-library` skill's search, only if `paths.broll_library_dir` is set) for a clean
hero shot of the subject.

The subject must be recognisable: a product from the front with its screen lit, not
its back; a place from its famous angle. If no frame holds what a concept needs (the
face and the subject together, a lit front), say so and suggest a 10-second pickup
shot. Don't fake it.

**Title-my-frames mode.** If the user hands you frames ("I grabbed these, put titles
on them"), skip to step 4 and use them as given, in their order.

### 3. Sample candidates

```
python3 $S/sample_frames.py --outdir <work>/frames --start <s> --end <e> --top 24 <clip> [<clip> ...]
```

One call per time window. It scores sharpness (ranked within each clip), penalises
black or blown-out frames, drops near-duplicates, and writes full-resolution frames plus
numbered contact sheets. **Read every contact sheet.** You judge what the score can't:
eyes open, a real expression, mouth not mid-word, the subject recognisable at tile size.
Then Read the full-size frame of each pick before you use it.

### 4. Concepts (three or more, genuinely different)

- **Face + subject + question.** The speaker holding or looking at the subject, a
  verdict or question beside them.
- **Subject hero.** The subject alone, big, well lit, clean background.
- **A-vs-B split** for any comparison or upgrade video: one word per side.
- **More when the footage earns it:** the reveal, the reaction, the problem shot.

Distinct images, same style (font, size, accent position) across the set.

### 5. Composite

Read [reference/design.md](reference/design.md) the first time (safe zones, picking,
titles, labels, retouches). Options: `python3 $S/compose_thumbnail.py --help` and the
script's header.

```
python3 $S/compose_thumbnail.py <frame.jpg> --format landscape --title "WORTH|IT?" \
    --accent-line 1 --align right --focus 0.35,0.45 --guides --out <work>/face-question.jpg

python3 $S/compose_thumbnail.py <a.jpg> --split <b.jpg> --format landscape \
    --focus 0.5,0.5 --focus2 0.55,0.6 --zoom2 1.4 --title VS --pos center --max-size 110 \
    --scrim none --label "OLD@0.25,0.2" --label "NEW@0.75,0.2" --guides --out <work>/split.jpg
```

- `|` breaks lines; `--accent-line N` colours line N (0-based) in the accent colour.
- **One font size across the set:** compose the longest title first, read `title_px`
  from its output, pass it as `--max-size` to the rest.
- **Look at `_guides.jpg` and `_feed200.jpg` for every composite.** Text inside the green
  box; the subject not under the red box (duration badge on landscape, feed crop on a
  Short); readable at 200 px. Act on every `warning`.
- **Brightness.** Below a centre brightness of 90 it warns "dark": re-run the same
  command with `--grade 1.5`, compare the two, keep the brighter one unless it looks
  hazy. A dark backdrop behind a lit subject is fine; a subject in shadow is not.
- **Retouch in the command, never by hand** (`--fill-box` for text on a screen,
  `--blur-box` for serial numbers and labels). The command is the record, and every
  run is appended to `compose-log.txt` next to the output.

### 6. Check: you, then one refuter

1. **Privacy pass, yourself.** Zoom into every screen, device back, document, sign and
   plate in each frame you used:
   `ffmpeg -v error -i <frame> -vf "crop=iw/4:ih/4:<x>:<y>,scale=iw*4:-1" -y <work>/zoom.jpg`
   then Read it. Fix leaks with `--fill-box` / `--blur-box` and re-compose. What counts
   as a leak is listed in `.claude/agents/thumbnail-refuter.md`.
2. **One `thumbnail-refuter` agent** for the round. Give it the composites, their
   `_guides.jpg` and `_feed200.jpg` (absolute paths), the format, a one-line summary of
   the video and the subjects it shows, the reference photos when AI candidates are in
   the round, and an output path for its JSON. If that agent
   type isn't available, spawn a general-purpose agent with the file's body as its prompt.
   It reports publish-regret faults only; taste is the user's.
3. **Triage.** A real fault: fix it with a compose flag or another frame. An objection
   you judge wrong: overrule it with a one-line reason in your report. The refuter never
   holds up showing the user the candidates.

### 7. Optional AI round

Only if the user has an image-generation tool (one available in this session, or one
their preferences name). Otherwise skip it without comment. How:
[reference/ai-round.md](reference/ai-round.md). The rule that matters: **an AI thumbnail
must show the exact product/subject model from the video, checked against the reference
photos. A lookalike is rejected, never shipped.**

### 8. Pool, sheet, pick

```
python3 $S/thumb_pool.py add <dest> own <work>/face-question.jpg <work>/split.jpg ... \
    --concepts "face WORTH IT?" "split OLD VS NEW" --note "see compose-log.txt"
python3 $S/thumb_pool.py add <dest> ai <ai images...> --concepts "..."   # fitted to size
python3 $S/thumb_pool.py sheet <dest>
```

Read `CANDIDATES.jpg`, show it to the user with one line per id (concept, hook, where
the frame came from, any flag) and the absolute path of each file. Offer to open the
folder (`open` on macOS, `explorer` on Windows, `xdg-open` on Linux). Tip for a new
user: in Finder, select the images and press **Space** (Quick Look), then the arrow
keys, to flip through them full size. Ask: "Pick up to three, best first, e.g. `O2 A1 O3`."

```
python3 $S/thumb_pool.py pick <dest> O2 A1 O3
```

The picks become `<dest>/thumb-1..3` in that order; an existing thumb-N is moved into
`thumbnail-candidates/replaced/` first, never overwritten. A Short takes one pick.

### 9. Set it on YouTube (the user does it)

- **With the upload:** youtube-release's paste sheet lists `<dest>/thumb-1.jpg`
  for the Details page.
- **Already uploaded:** YouTube Studio -> Content -> the video's pencil (Details) -> Thumbnail ->
  Upload file. If the Thumbnail block offers a test of several thumbnails (YouTube's
  A/B "Test & compare"), upload thumb-1..3 there. Custom thumbnails need a verified
  channel (a one-time phone check at youtube.com/verify). A Short's custom thumbnail
  may not show everywhere (the Shorts player often shows a frame of the video), so the
  Short's first frames still matter.

### 10. Report

Per candidate: id, absolute path, size in MB and pixels, concept, hook, frame source.
What the privacy pass and the refuter caught and what you changed. The pick and where
thumb-1..3 landed. Which font and engine were used. Whether it was set on YouTube.

## Restyle any time

"Bigger text", "my brand font", "red instead of yellow", "put the text on the left":
re-run the commands from `compose-log.txt` with the changed flags, add the results to
the pool (they get new ids; nothing is overwritten), rebuild the sheet. If it sounds
lasting, add one bullet under `## youtube-thumbnails` in `user/preferences.md` and say
so in one line. A font for every video goes in the `youtube.thumbnail_font` setting.

## Hard rules

- **Real pixels for our own concepts.** Every non-AI thumbnail is a frame (or two) of
  the footage, with titles and retouches from `compose_thumbnail.py`. Never generate or
  AI-edit a face or a product into them.
- **Exact canvas, under 2 MB, JPG or PNG.** The scripts enforce it.
- **Never claim what the video doesn't say**, in text or in an AI image.
- **Privacy beats everything:** no readable notifications, messages, names, addresses,
  routes, plates, serials or account details. When unsure, cover it.
- **Nothing is uploaded or set without the user's explicit go**, and you Read every
  final image before it goes anywhere.
- **Never overwrite a delivered thumbnail;** the pool only grows.
- **Read media, never write it.** Work files go in the `work` folder from `info`.
- **One ffmpeg job at a time,** and not while a big render is running.

## What the user can customize

Font, colours, text side, words per title (preferences or the setting); which concepts
to make every time; whether to run the AI round; the refuter's model (in
`.claude/agents/thumbnail-refuter.md`); anything else through the `customize` skill.
