# Titles, descriptions and the upload

Long-form titles are written for search: someone types a query and picks from a
list. Shorts titles are read while the video is already playing, so the title's
job is to confirm what the viewer is seeing and give the topic a name.

Write from two sources only: the short's own words (what the viewer hears, in
order) and the full long-form transcript (names, numbers and context the short
leaves out). Every number or claim must be traceable to one of them.

## Title (hard limit 100 characters; the player shows about the first 40)

- Open on the concrete thing: "Lock your exposure before you film", not
  "You won't believe this trick".
- Numbers beat adjectives ("10 seconds", "3 changes").
- Name the product or the topic: that is the search phrase and what links the
  short to the long video.
- The first 2 seconds of the short must pay the title off.
- No ALL CAPS, at most one emoji and never first, hashtags go in the description.
- Several shorts from one video: give each its own search phrase (`keyword` in
  the proposal) so they do not compete with each other or with the long video,
  and never reuse the long-form title.
- Offer the user 2-3 options per short with a recommendation.

## Description (300-800 characters is plenty)

1. One or two sentences of payoff (only the first line shows in the feed).
2. A link to the full video once it is public (the point of making Shorts).
3. Links only to things that appear in this short. If any link earns the user
   money (affiliate, sponsor), say so right after the links: it is a legal duty
   in many countries, and `check_metadata.py` flags a description without it
   as an error.
4. Up to 3 hashtags, one of them `#shorts` (optional: a video is a Short because
   it is vertical or square and at most 3 minutes, not because of the tag).

Leave out timestamps (Shorts have no chapters) and the long video's full
credits or product list.

## The upload (the user does it)

```
python3 ${CLAUDE_SKILL_DIR}/scripts/check_metadata.py <short.mp4> --title "..." --description-file <desc.txt>
```

- Hand the user the short's absolute path, the title and the description. They
  upload it in YouTube Studio (Create > Upload videos) or the YouTube app; a
  vertical video of 3 minutes or less becomes a Short by itself.
- Privacy is their choice; suggest settings `youtube.default_privacy`
  (`unlisted` is the safe choice for a first look).
- YouTube cannot replace a video's file after upload: every fix is a new upload.
  That is why QC and the user's review come first.
- Ask for each short's link once it is up, for the long video's description or
  a pinned comment.
