# Where montage music can come from (and what each allows)

Not legal advice: check each track's licence page before publishing.

| Source | Cost | Published video? | Notes |
|---|---|---|---|
| The user's own music folder (`paths.music_dir`) | - | only what they hold rights to | bought downloads are usually licensed for personal use, not for publishing |
| YouTube Audio Library (YouTube Studio > Audio library) | free | yes, on YouTube; some tracks require the credit line shown | filter by mood, genre, instrument, duration; download button per track |
| Creative Commons tracks (Free Music Archive, ccMixter, incompetech, Pixabay Music...) | free | yes, under the track's licence | CC BY = credit the artist; NC = non-commercial only; ND = no edits (cutting a track can count as an edit) |
| Paid royalty-free libraries (subscription or per track) | paid | yes, per the plan's terms | check whether the licence covers monetised videos |
| Music the user made, or friends with written permission | - | yes | keep the permission |

## Downloading

Prefer the source's own download button. `pull.py` (yt-dlp) is for the cases where a track the
user may use is only offered as a stream (for example their own upload). It refuses to run without
a `--rights` line and logs URL, licence and date to `SOURCES.tsv` beside the track.

## Content ID, in one paragraph

YouTube matches uploads against registered music. A commercial song in a home video gets the
video claimed (ads go to the rights holder), muted, or blocked in some countries, even when
unlisted. That is why a video that will be uploaded anywhere needs licensed music from the start:
swapping music after a claim means re-cutting to a new beat grid.

## Credits

For CC BY tracks, put the credit line in the video description (and keep it in
`SOURCES.tsv`): "Track - Artist (source URL), licensed under CC BY 4.0".
