# Optional AI round (ids A1, A2 ...)

Extra candidates from an image-generation model, built from REAL reference photos of
the speaker and of the exact subject. They join the pool next to the real-footage
concepts and the user picks from both. They never replace the real-footage concepts.
`$S` is the skill's `scripts/` folder.

## When to run it

- Only if an image tool is available: an image-generation tool in this Claude session
  (for example an MCP server the user connected), or a tool their preferences name
  (a command-line tool, or a website they use by hand: then you write the prompts and
  they save the images into a folder for you).
- No tool and nothing in preferences: skip the round and don't mention it.
- **First time only, ask before sending the user's face to an online service.** It is
  their likeness; some people don't want it uploaded. Remember the answer as a
  preference bullet.
- Never use a paid service the user hasn't set up and approved.

## 1. References (real frames, no text)

- **The face:** a sharp frame from the footage, eyes open, looking into the lens, ideally
  holding the subject. Not a composited thumbnail (no title text on it).
- **The exact subject:** a clean frame of *this* model from the front, lit, filling the
  frame. For a comparison, one reference per subject.
- Save them in `<work>/refs/`, at most 1920 px wide:
  `ffmpeg -v error -i <frame> -vf "scale='min(1920,iw)':-2" -y <work>/refs/face.jpg`
- Zoom into the references first: anything private in them (a screen, a street sign)
  can be reproduced by the model.

## 2. Prompts: one concept per image

Ask for the target shape (16:9 for long-form, 9:16 for a Short). A template:

> YouTube thumbnail, 16:9, photorealistic, high contrast. Use the person from image 1
> exactly as they are: same face, same hair, same clothes. <pose and expression>. The
> <subject> must match image 2 exactly: <its size, proportions, colour, what is on its
> front, left to right>. Do NOT draw <the older or more common model it gets confused
> with, and how that one looks>. <background, light>. Big bold text <where>: "<HOOK>",
> "<word>" in yellow, "<word>" in white, thick black outline. No other text.

- The text is the same 1-3 word hook as the real-footage concepts. Never claim what the
  video doesn't say, and don't depict results or events the video doesn't show.
- Good concepts: both subjects side by side and labelled with the winner glowing; the
  speaker's reaction to the problem the video solves; the subject held at chest height
  with the verdict; a calm "fixed it" pose with the subject in the foreground.

## 3. The exact-model rule

Image models drift toward the older, more photographed version of a product, or a
generic lookalike. Viewers who own the real thing notice at once, and it misrepresents
the video.

- **Check every image against the reference photos:** shape, proportions, size relative
  to the hands, ports and buttons, logo placement, colour, screen layout. Zoom in.
  A lookalike or an older model is rejected, never shipped, however good the rest is.
- In the prompt, spell out the geometry (size, height as a share of width, what the front
  carries) and name the wrong model to avoid.
- **Asking for an edit rarely fixes a wrong product:** the edit keeps the composition and
  the wrong object with it. Start a fresh image with the subject large and close to the
  camera, and point at an earlier result that got it right.

## 4. Check each image before it counts

- Right model (section 3); text spelled right and printed once; no gibberish text on
  screens; hands and fingers plausible.
- Likeness: if the face looks off, say so in the sheet line; the user decides.
- Nothing private legible (generated screens can copy real details from the references).
- Rejects are not filed. Keepers only.

## 5. File them

```
python3 $S/thumb_pool.py add <dest> ai <image> [<image> ...] --concepts "<concept 1>" "<concept 2>"
```

`add` centre-crops and resizes anything that isn't exactly 1280x720 / 1080x1920 and
re-encodes it under 2 MB, so any tool's output size works. Keep the full-size originals
in `<work>/ai/` if the user may want a different crop later.

Using AI help on a thumbnail is a choice the user makes for their channel; if their
platform asks about synthetic or altered content at upload, that question is about the
video itself. When unsure, point them to YouTube's current help page rather than guessing.
