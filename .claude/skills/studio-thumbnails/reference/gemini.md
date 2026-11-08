# Gemini round (G-ids)

The other generated half of the pool, next to Ask Studio's three. Gemini's image model
(gemini.google.com, image generation, the user's own Google account in Chrome) takes
**real reference photos** (the speaker's face, the exact product), so the likeness and the
product come out right more often than Ask Studio's, which works only from the video.

It doesn't need the upload, so it can run any time after the real-footage thumbnails
exist. It needs about 25 s per image, so five concepts take about 5 minutes with the
downloads. Ask once, the first time, before uploading the user's face anywhere.

## 1. References (scratchpad, ≤1920 wide)

- **The face:** a real a-roll frame looking into the lens, ideally holding the product
  (`youtube-thumbnails`' work frames under `<project>/<work>/thumbnails/<round>/`, e.g.
  `face-*.jpg`). No text on it.
- **The exact product:** a clean real frame of *this* model, the front visible, no title
  text (a sampled frame, not a composited `own-N`).
- `cp` both into the scratchpad, `sips -Z 1920` (macOS) or any resize. `file_upload` only
  takes the session's own folders.

## 2. Open, 16:9, attach

1. A NEW tab → `https://gemini.google.com/images` (or the image-generation entry Gemini
   shows in your region).
2. **Aspect ratio** under the prompt box → **16:9** (9:16 for a Short).
3. Patch the hidden file input first. "+" → **Upload files** calls `click()` on it, which
   would open the native picker the extension cannot drive:
   ```js
   window.__origClick = HTMLInputElement.prototype.click;
   HTMLInputElement.prototype.click = function () {
     if (this.type === 'file') { this.setAttribute('data-captured','1'); if (!this.isConnected) document.body.appendChild(this); return; }
     return window.__origClick.call(this);
   };
   ```
4. "+" → **Upload files**. Then `find` "file input element type=file". The captured input
   has `data-captured="1"` in a `javascript_tool` listing. `file_upload` **both files in one
   call**, face first. They are "image 1" and "image 2" in the prompts.

## 3. One concept per message, same chat

The references stay in context for the whole chat, so each later message names a new
concept and says "same rules". Template for the first:

> YouTube thumbnail, 16:9, photorealistic, high contrast. Use the person from image 1
> exactly as they are: same face, same hair, <their clothes in the frame>. Keep their
> likeness. <pose + product>. The <product> must match image 2 exactly: <size, proportions,
> the front's ports/buttons left to right>. Do NOT draw <the older model it gets confused
> with, and how that one looks>. <background, light>. Big bold text <where>: "<HOOK>", with
> "<word>" in yellow and "<word>" in white, thick black outline. No other text.

- **Text** is the speaker's verdict cut to 1-3 words, the same rule as the real-footage
  concepts. Never claim what the video doesn't say.
- **Concepts that work:** both products side by side, labelled, the new one glowing, the
  speaker pointing at it ("1.5x"); the speaker frustrated, the old product on the desk, a
  red graph behind them ("ISN'T ENOUGH"); the speaker holding the product at chest height
  ("FASTER"); the speaker leaning back relieved, product in the foreground ("FIXED IT").

## 4. The wrong-product trap

Gemini drifts to the older, more photographed design of a product (a redesigned desktop
computer comes out as its wide flat predecessor; a round watch as the squircle one). Users
reject that on sight.

- Spell out the geometry: size, height as a share of the width, what the front carries,
  and name the wrong model ("NOT the old wide flat one").
- **An edit doesn't fix it.** "Redo it with the new one" keeps the composition, and with
  it the wrong product. Start a fresh image ("Brand new image, start over"), with the
  product large and close to the camera. Point at an earlier result that got it right.
- Zoom on every product before it counts (`computer zoom` on the image), against the
  reference.

## 5. Download, one at a time

`date +%s` first. Then `find` "Download full size image buttons on generated images (in
order top to bottom)". For each keeper:

```
scroll_to <ref>
left_click an empty spot of the page (right margin)
hover <ref>
left_click <ref>
wait ~15 s, until a new Gemini_Generated_Image_*.jpeg is in ~/Downloads
```

The full-size file takes 10-15 s to prepare. Clicking the next before the file lands loses
downloads and scrambles the order the collector relies on. Skip the rejects (wrong
product, garbled text). The pool keeps keepers only.

## 6. File them

```
python3 ${CLAUDE_SKILL_DIR}/scripts/collect_gemini_thumbs.py --since <epoch> \
    --dest <dest from thumb_pool.py info> \
    --work <project>/<work>/thumbnails/<round>/gemini \
    --concepts "<concept 1>" "<concept 2>" ...
```

Downloads are 2752x1536 JPEGs of about 2.2 MB, over YouTube's 2 MB cap. `thumb_pool.py`
centre-crops each to 1280x720 (1080x1920 when vertical) and re-encodes under the cap, as
`gemini-N-<concept>.jpg` = G1, G2 … Then the collector moves each full-size original into
`--work` as `gemini-N-<concept>-full.jpeg`. It refuses when the count doesn't match
`--concepts`. Close the tab when done.

## 7. Check before the sheet

Read every G image. Check that it is the right product model, the text is spelled right and
printed once (a word can print twice), the likeness is good, and nothing private is legible.
Faults go in the hand-over next to the id, the same as Ask Studio's.
