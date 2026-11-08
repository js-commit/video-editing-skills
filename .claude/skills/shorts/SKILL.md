---
name: shorts
description: Cut vertical YouTube Shorts (9:16, 1080x1920 by default, 2160x3840 for 4K) out of a finished long-form video - an agent proposes word-precise cut lists with a hook in the first 2 seconds, the user picks, a framing agent reframes every shot (crop on the subject, fit over a blurred backdrop, face-over-subject stacks, b-roll swaps) so the face-only time stays low, ffmpeg renders it with burned-in word-by-word captions, a measured QC checks length, loudness and the Shorts safe zones, and it uploads only on the user's go. DaVinci Resolve Studio users can get the short as an editable vertical timeline instead. Use for "make shorts from this video", "cut a short / a TikTok / a Reel", "vertical version of my video", "highlights for Shorts", "shorts from my Resolve edit", and for notes on a short this skill made.
argument-hint: "<finished long-form video> [how many shorts, topic, 4K]"
---

# Shorts

Makes vertical Shorts from a video that is already edited. The long-form's audio
is the voice of the short (cut at word boundaries, never mid-word), its pictures
are reframed shot by shot, and b-roll from the project or the b-roll library fills
the moments where the long-form only shows a talking head. Output: one MP4 per
short in the project's drafts folder, plus its spec (the recipe, editable JSON),
plan, captions and a QC sheet.

New to Shorts? `reference/craft.md` explains in two pages what makes a Short work
and where the YouTube app covers the picture. Tell the user the one or two points
that matter for their video, in plain words, unless preferences say they know.

## Before you start

- Read `user/preferences.md`: `## shorts` and `## general` override every default
  here (resolution, caption look, how many shorts, length, face budget, upload
  privacy, ffmpeg vs Resolve). Typical lines: "4K shorts (2160x3840)", "captions
  in my brand yellow, no uppercase", "always propose 5".
- Check ffmpeg: `python3 tools/vidkit/media.py check` (it reports whether this
  ffmpeg has `subtitles`/libass for the nicest captions; drawtext is the fallback).
- The Resolve path needs `editor.nle` = `resolve-studio`
  (`python3 tools/vidkit/settings.py get editor.nle`; unset = ask). Everyone else,
  and Resolve users who just want a file, get the ffmpeg path.

Scripts live in `${CLAUDE_SKILL_DIR}/scripts/` (call it `K`). Every script has `--help`.

## Steps

1. **The source and its transcript.** The input is the finished long-form render
   (the master), not the raw footage. Get its word-level transcript:
   `python3 tools/transcribe.py <master>` (prints the `<stem>.transcript.json`
   path; reuses it when it exists). Work folder: `python3 $K/proposals.py workdir <master>`.
   Specs from earlier rounds in that folder mark passages already used: tell the
   scout to avoid them.

2. **Scout.** Spawn the `shorts-scout` agent with: the master path, the transcript
   path, the work folder, how many shorts (default 3, or preferences), the topic
   if the user named one, and the burned passages. It writes
   `<work>/proposals.json` and runs `proposals.py check` until it passes. If the
   agent type is not available, use a general-purpose agent with model opus and
   paste `.claude/agents/shorts-scout.md` into its prompt.

3. **The user picks.** Show a table (slug, seconds, hook words, title, angle) and
   the prose of each (`python3 $K/proposals.py text <work>/proposals.json`): the
   user should hear the short in their head. Ask which to make. Never render all
   of them unasked.

4. **Specs.** `python3 $K/proposals.py spec <work>/proposals.json --pick a,b --size 1080x1920`
   (use the preferences' size, e.g. `2160x3840`). Copy any caption style from
   preferences into each spec's `caption_style` (keys in `make_short.py --help`).

5. **B-roll (optional, recommended).** Collect candidates before framing:
   the project's footage folder (`python3 tools/vidkit/settings.py get project_layout.footage`),
   and the b-roll library if the user has one:
   `python3 .claude/skills/broll-library/scripts/search.py "<subject nouns>" --limit 8 --json`
   (an empty list just means no library). Search by what is talked about (the
   product, the place, the action), one query per short.

6. **Framing.** Spawn the `shorts-framing-director` agent with the spec paths, the
   master, the transcript, the work folder and the b-roll candidates. It writes
   each shot's framing into the specs, renders, runs QC and leaves
   `<work>/framing-plan.json`. (Fallback as in step 2, model sonnet.)

7. **Render and QC** (the director already did; re-run after any change):
   ```
   python3 $K/make_short.py <work>/<slug>.spec.json
   python3 $K/qc_short.py <drafts>/<slug>.mp4 --sheet <work>/<slug>.qc.jpg
   ```
   QC exit 3 = fix and re-render. Then Read the sheet: subject framed, nothing
   important under the red UI zones, captions readable. For a final check of the
   cut points, transcribe the render (`python3 tools/transcribe.py <drafts>/<slug>.mp4`)
   and pass `--render-transcript` to the QC: the first word must be the hook's.

8. **User review.** Give the absolute paths of each MP4 and its QC sheet, the hook
   line, length, face-only share and anything QC warned about. If the user reviews
   in EditReview, its `notes.json` (next to the render, in `<stem>.review/`) maps
   to spec changes: framing notes edit `framing`, "cut this" / "start later" edit
   `segments` (new boundaries are word starts / ends from the transcript). Re-render, re-QC.
   Record lasting corrections in preferences.

9. **Title, description, and the user's upload.** Write the title and
   description from the short's own words (`reference/metadata.md`), check them:
   `python3 $K/check_metadata.py <mp4> --title "..." --description-file <work>/<slug>.description.txt`
   then hand the user, per short, the MP4's absolute path, the title and the
   description text. They upload it in YouTube Studio (or the YouTube app on
   their phone) and pick the privacy; suggest settings `youtube.default_privacy`
   (unlisted). Nothing here uploads.

## The Resolve option (DaVinci Resolve Studio)

Same steps 1-6, then build the short as a new vertical timeline in the project
that holds the long-form edit, from that timeline's own clips, so the user can
keep editing it. Details and caveats: `reference/resolve.md`.
```
python3 $K/resolve_short.py snapshot <spec> --project "<project>"          # backup first
python3 $K/resolve_short.py create <spec> --project "<project>" --long-timeline "<edit>" --dry-run
python3 $K/resolve_short.py create <spec> --project "<project>" --long-timeline "<edit>"
python3 $K/resolve_short.py stills <spec> --project "<project>" --name "short - <slug>" 0.5 1.5 10 20
```
Ask the user to save their work first: loading the project switches Resolve to
it. Show them the new timeline (Edit page, Shift+4; play with Space, J/K/L to
shuttle). Render with `resolve_short.py render` or by hand on the Deliver page
(Shift+8), then QC the file like any other render.

## Rules (general lessons, keep them)

- **Every cut sits on a word boundary.** Start = the start of the first word, end
  = the end of the last, copied from the transcript; the renderer then moves each
  cut into the quietest 10 ms of the gap next to it and fades the join over 8 ms.
  Never trust a proposal's numbers without `proposals.py check`.
- **The hook comes first and lands inside 2 seconds.** The first words name the
  subject or make a claim; a sentence that starts "so", "and" or "for example"
  is a continuation, not a hook. A short may open on a later passage and go back.
- **Self-contained.** Every pronoun has its antecedent inside the short; restore
  the setup sentence a payoff depends on; end where a sentence ends, on a payoff,
  a verdict or a question, never mid-thought. Read the short as prose before
  rendering.
- **Length follows the material:** 15-60 s is the sweet spot; a tight 25 s short
  beats a padded 55 s one. Over 3 minutes is not a Short at all.
- **Different angles, not trims.** Several shorts from one video each take a
  different passage and a different search phrase.
- **Face budget:** face-only shots (nothing but the speaker) at most 20 % of the
  runtime (preferences may change it). The face with the subject, or a stack of
  face over subject, does not count. Fill with b-roll that matches the words.
- **Vary the framing every few seconds** (wide, crop, punch-in, stack, b-roll); no
  shot over about 8 s, none under 1 s (a sub-second shot reads as a glitch).
- **Text lives in the middle band**, inside the safe area: never under the top
  8 %, the bottom 22 % or the right-hand 13 % of the frame (the app's buttons and
  title cover them), never across the face or the subject.
- **Open on the sharpest, most active picture**, not a soft or dim one.
- **Captions on every short:** most Shorts are watched muted.
- **Strip metadata** (the renderer does): phone clips carry GPS tags.
- Re-render to a new name or version when a file is open in Resolve: Resolve
  keeps a replaced file's old length and picture cached under the same path.

## Hard rules

- Nothing is uploaded or published without the user's explicit go for that short.
- Never overwrite the long-form or any source media; renders go to the drafts
  folder. The Resolve script only creates timelines whose name starts with "short".
- Confirm the list of shorts with the user before rendering.

## What the user can customize

Everything above is a default. Common changes (record them under `## shorts` in
`user/preferences.md`; deeper changes through the `customize` skill):
output size; caption font, size, colours, uppercase, position (`caption_style`);
how many shorts the scout proposes and their length; the face budget; loudness
target (`lufs`, default -14); default upload privacy; ffmpeg or Resolve.
