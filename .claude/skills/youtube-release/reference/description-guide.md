# Titles, descriptions, chapters, tags, links

The user's own style in `user/preferences.md` (`## youtube-release`) overrides
everything here.

## Titles

- Write 3-5 options in `titles.txt`, one per line, the recommended one marked
  with a leading `*`, and one line of why each when you show them.
- Lead with what people search for (the topic or product), then the hook (what
  makes this video worth clicking: a test, a result, a number). Phones show
  about 60-70 characters; YouTube's hard limit is 100.
- Promise only what the video delivers. Every fact comes from the transcript.
- No `<` or `>` (YouTube rejects the upload).

## Description: block order

YouTube shows about two lines before "...more", so the order matters.

1. **Hook, 1-2 lines**: the promise of the video. No links here.
2. **Links** (if any): `links.txt` from `metadata.py draft`, which only
   contains links from `user/links.md`. A disclosure line follows when links
   are included (see below).
3. **Chapters** (`chapters.txt`, validated).
4. **The substance**: what the video found, measurements, the verdict,
   caveats. Worth indexing, worth reading.
5. **A question for the comments**: reuse the one asked on camera if there is
   one.
6. **Credits**: music and footage licences that require attribution (CC BY
   needs title, author, source and licence).
7. **Hashtags, up to 3**: the first three show above the title.

Limit: 5000 bytes (an emoji is 3-4 bytes). 1000-2500 characters is plenty.
Put no other times at the start of a line, or YouTube reads them as chapters.

## Chapters

Chapters split the progress bar into named sections, let viewers jump to the
part they want, and show up in search. YouTube shows them only when:

- the first time is `00:00`,
- there are at least 3,
- every chapter is at least 10 seconds long (one short chapter hides all of them),
- the times go up.

`metadata.py chapters propose` suggests starts at the longest pauses: a
starting point. Read the transcript around each one, move it to where the
topic really changes, and name each chapter for what it covers ("Brightness
test", not "Part 3"). 30 s to 3 min per chapter reads well. `metadata.py
chapters validate` and `metadata.py check` enforce the rules.

Times must be on the clock of the uploaded file: build them from a transcript
of the final master, never of the raw footage.

## Tags

Tags are a weak signal today; spend a minute, not ten. 5-15 tags: the main
topic, the product or place names, common misspellings. 500 characters in
total, and a tag with a space costs two extra. `notes.md` lists candidates.
Never add unrelated popular tags: YouTube can lock videos with misleading tags.

## Links: `user/links.md`

The user keeps their own links in `user/links.md` (never committed). The skill
never invents a link: `metadata.py check` refuses any URL that is not in that
file, unless the user just gave it to you (`--allow-url`). Format:

```
# My links
## always
- My website: https://example.com
- Second channel: https://example.com/second

## gear
- Camera A: https://example.com/camera-a (keywords: camera a, my camera)
- Desk lamp: https://example.com/lamp

## disclosure
Some links are affiliate links: I may earn a commission at no extra cost to you.
```

- `## always`: added to every description.
- Any other section: a link is included when its label (or one of its
  `keywords`) is said in the video.
- `## disclosure`: added under the links whenever a matched link is included.
  Affiliate links and gifted products need a clear disclosure where viewers
  see it, near the links (in the US the FTC requires it; most countries have a
  similar rule).

If the file does not exist, the description simply has no links block. Offer
once to start the file for the user.

## Declarations at upload

- **Made for kids**: a legal declaration (COPPA in the US). Saved once in
  settings `youtube.made_for_kids`; ask the user the first time, never guess.
- **Altered or synthetic content**: yes only for realistic AI-generated or
  altered people, places or events. AI help with titles, thumbnails, scripts or
  captions does not count. Settings `youtube.contains_synthetic_media` (your
  standing answer, shown on the paste sheet), or answer it in Studio per video.
- **Category**: settings `youtube.category` (a name like `Education` or an id).
- **Language**: settings `youtube.language` (helps captions and translations).

## Privacy, in one line each

- **Public**: anyone can find and watch it.
- **Unlisted**: anyone with the link can watch; it never shows in search or on
  your channel page. Right for review links and family videos.
- **Private**: only you (and people you invite by email) can watch it.
- **Scheduled**: uploaded private, goes public by itself at the time you set
  in Studio (Visibility > Schedule).
