---
name: studio-thumbnails
description: The generated half of a thumbnail pool - three AI thumbnail concepts for a video already uploaded to your channel from YouTube Studio's Ask Studio (attach the video, ask, download through the Chrome extension, filed as S-ids), plus an optional Gemini round (gemini.google.com with a real photo of the speaker's face and of the exact product as references, one concept per message, filed as G-ids), all in the video's thumbnail-candidates/ pool beside the real-footage thumbnails (youtube-thumbnails), where the user picks the top three. Free with a YouTube channel / Google account; Ask Studio is slow (2-3 minutes per generation), Gemini about 25 s an image; generated products drift to older models and must be checked. Use after the upload of a release or Short, or when asked for "Ask Studio thumbnails", "Gemini thumbnails" or "more AI thumbnail variations with my face".
argument-hint: [video title] [dest folder]
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/collect_studio_thumbs.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/collect_gemini_thumbs.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/../youtube-thumbnails/scripts/thumb_pool.py *), Bash(sips *), Bash(date *), Bash(ffmpeg *), Bash(open *)
---

# Thumbnails from Ask Studio (and Gemini)

Ask Studio (the sparkle button top right in YouTube Studio) reads the video's own frames,
title and the channel's style and generates three thumbnail *concepts*: the speaker and the
product re-staged, bold two-tone text, a named idea per concept ("Split-Screen Comparison",
"3 Elements", "Don't Do This"). The work here is driving the chat, getting the files out,
and filing them.

**One half of the pool.** These join the real-footage thumbnails (`youtube-thumbnails`) in
the video's candidate pool and the user picks from both. **Optional Gemini round:** after
Ask Studio, the same browser session asks Gemini for about five more concepts built from a
real photo of the speaker's face and of the exact product ([reference/gemini.md](reference/gemini.md)).
Generated faces can look off, so these never go straight into `thumb-N`. The pool, sheet and
pick are owned by `youtube-thumbnails`, section *Pool, sheet, pick*.

**Needs:** the Claude in Chrome extension (`claude-in-chrome` skill) with the user signed in
to YouTube Studio (and Gemini for the second round). No extension: skip this skill and say
so; the real-footage thumbnails stand alone.

**Hard rules**

- **The video must already be on the channel.** Ask Studio works from the upload, so this
  comes after the upload (unlisted is fine: the video picker lists non-public uploads). A
  video still processing may not be listed yet; wait and reopen the picker.
- **Nothing is applied to the video here.** Each image offers only Download and Copy.
  Setting thumbnails is a separate, deliberate step (`youtube-thumbnails`, *Set it on YouTube*).
- **Look at every image before it goes anywhere.** They are generated, not frames: check
  that the product is the right model and shape, the text is spelled right, screen text
  isn't gibberish, and nothing private shows (a generated device screen can carry real
  content from the video: a map, a notification). Wrong product or leaked detail means ask
  again, not ship.
- **Never overwrite a delivered thumbnail.** The pool is append-only: a second round
  continues the numbering (S4-S6).
- **AI thumbnails do not make a video "altered or synthetic content".** YouTube lists
  generative-AI help on a thumbnail as production assistance, no disclosure
  (support.google.com/youtube/answer/14328491); the upload's Altered content answer stays No.
- **First time only, ask before sending the user's face to Gemini.** It is their likeness;
  remember the answer as a preference bullet under `## studio-thumbnails`.
- Right channel: the Ask Studio panel greets the channel by name. Anything else, switch
  account from the avatar first.

## 1. Open Ask Studio

Load the claude-in-chrome skill; `tabs_context_mcp`, then a NEW tab →
`https://studio.youtube.com`. Click **Ask Studio** in the top bar. If the panel opens on an
old chat, click the **New conversation** pencil (top right of the panel) so a previous
video's context doesn't bleed in. **No Ask Studio button** (the feature is not on every
channel or in every region): say so and skip to the Gemini round (§6).

## 2. Attach the video and ask

1. **+** (bottom left of the input) → **Select your video** → type part of the title in
   *Search your video* → click the row. A thumbnail chip with the duration appears above the
   input. Attaching is exact; naming the title in the prompt also works but can pick the
   wrong one of two similar titles.
2. Click the input, type `Create 3 thumbnails for this video`, press Return. Steering is
   welcome in the same message: the verdict, the text to use, what must be in frame ("both
   products, fronts visible"). **+** → **Upload images** attaches reference images.
3. **Wait: it is slow, 2-3 minutes per generation.** The status line walks *Just a sec →
   Getting specific details → Gathering visual assets → Choosing the best options →
   Creating your thumbnails → Adding final touches*; a stage can sit for a minute, which is
   normal, not a hang.
   - **Use the wait.** Ask first, then do other work between checks (title, description,
     `date +%s` for step 3). Don't hold the turn with back-to-back screenshots.
   - **Done check, no screenshot needed:** `javascript_tool` on the tab:
     ```js
     function* walk(r){for(const e of r.querySelectorAll('*')){yield e; if(e.shadowRoot) yield* walk(e.shadowRoot);}}
     const els=[...walk(document)];
     ({images: els.filter(e=>e.tagName==='YTCP-GENERATED-IMAGE-VIEW-MODEL').length,
       done: els.some(e=>e.getAttribute?.('aria-label')==='Good response')})
     ```
     Done = `images` went up by 3 (a follow-up round in the same chat keeps the earlier
     ones, so compare with the count before asking) and the Good/Bad response buttons are
     there. Images below the fold lazy-load and stay grey until scrolled to, which doesn't
     matter for downloading.
   - Check every ~30 s. Don't click in the panel, start a new conversation, navigate the
     tab or close it while it works.
   - **Past 6 minutes** with no images, or an error line in the panel: screenshot, then
     ask once more in the same conversation. A second failure → tell the user and stop;
     don't loop.

The answer is three *Concept N: <name>* sections, each with a description, the image and
*Why it works*. Long-form concepts are 1365x768, a Short's are 768x1365; Studio picks the
orientation from the video. Note the three concept names for the collector.

## 3. Download the three

Record the time first: `date +%s`. Then `find` "Download buttons on generated thumbnail
images" (three refs, concept order) and do this per ref, top to bottom, in one
`browser_batch`:

```
scroll_to <ref>
left_click on the empty panel header (between the panel title and the pencil icon)
hover <ref>
left_click <ref>
wait 3
```

The plain click on the header is what makes it work: Chrome's download limiter drops a
second download from the same page unless a user gesture comes between them. The buttons
only render on hover; an image still grey from lazy loading downloads fine. Each lands in
`~/Downloads` as `IM<image-id>.png`, about 1.3 MB.

## 4. File them

```
python3 ${CLAUDE_SKILL_DIR}/scripts/collect_studio_thumbs.py --since <epoch from step 3> \
    --dest <dest from thumb_pool.py info> \
    --concepts "<concept 1>" "<concept 2>" "<concept 3>"
```

It takes the `IM*.png` downloads newer than `--since`, in download order, checks each is a
16:9 / 9:16 PNG, and adds them to the pool through `youtube-thumbnails/scripts/thumb_pool.py
add`, which fits them to YouTube's canvas (1280x720 / 1080x1920, under 2 MB), numbers them
S1, S2 ... after any earlier round and logs each to `thumbnail-candidates/INDEX.txt`. It
refuses when it finds anything other than three: it lists what it found, so download the
missing one or narrow `--since`. Each download leaves `~/Downloads` (the untouched original
is kept in `thumbnail-candidates/originals/`).

`<dest>` is the folder `thumb_pool.py info <video or project>` prints (the project's finals
folder); for a Short, the Short's own output folder.

## 5. Check them, then hand over

Read each of the three and run the check in *Hard rules*. Note any that re-stage the face
oddly or get the product wrong. Then continue with `youtube-thumbnails`, *Pool, sheet,
pick*: the sheet, the user's pick, and setting the picks.

The user wants something different: follow up in the same conversation ("concept 2 but
the text says KEEP THE OLD ONE", "more like concept 1"), and collect the new images again. They
join the pool as S4-S6.

## 6. The Gemini round (optional)

Right after Ask Studio's three are filed, before the sheet:
[reference/gemini.md](reference/gemini.md). In short:
- **References:** the speaker's face and the exact product, both real frames.
- **Format:** 16:9 (9:16 for a Short), one concept per message.
- **Product check:** spell out the product's geometry and name the old model it gets
  confused with. Start a fresh image rather than edit a wrong one.
- **Downloads:** one at a time.
- **Filing:** `python3 ${CLAUDE_SKILL_DIR}/scripts/collect_gemini_thumbs.py` → G1, G2 …

The sheet then carries O, S and G ids, and the user answers e.g. `G4 G1 S1`.

## Report

The pool files the collectors printed (S- and G-ids, paths, concept names, dimensions),
and anything the check flagged.
