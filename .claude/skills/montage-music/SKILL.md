---
name: montage-music
description: Score a montage with music the user has the rights to - choose 2-3 tracks that fit the story's moods from their own music folder or a royalty-free library, analyse beats and energy (librosa if installed, otherwise a built-in ffmpeg analysis), pick each cue's in-point (the band coming in, a hit aimed at a shot, a natural ending), set levels so the clips' own sound stays audible, and mix it all into one soundtrack. Use when asked to "find music for this video", "score this montage", "pick a song for this part", "different music for each day", "swap the intro song", "where should the song start", or "the music is too loud". home-video calls it for every montage.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffmpeg *), Bash(ffprobe *), Read, Write, Edit
---

# Montage music

Music carries a montage: it sets the mood, gives the cuts a rhythm, and tells the viewer when a
chapter starts and when the story ends. This skill decides **which** music and **where** it
starts; home-video's `make_draft.py` lays the cuts on its beats and calls `mixdown.py`.

```
M=${CLAUDE_SKILL_DIR}/scripts
python3 $M/find_music.py [--analyze]              # what is in the music folder: length, tags, tempo
python3 $M/analyze.py TRACK [--out F.json]         # tempo, beats, energy, entries, natural ending
python3 $M/analyze.py TRACK --profile 20 40 0.25   # loudness profile of a stretch: see the band come in
python3 $M/sample.py TRACK --in 12 --len 40 --out <project>/work/music-samples --label "Part 1 - A"
python3 $M/mixdown.py CUT.json OUT.wav             # music + the clips' own sound + featured moments
python3 $M/pull.py URL --name N --rights "why"     # optional yt-dlp download of a track you may use
```

## Before you start

- Read `user/preferences.md`: `## montage-music` holds the user's taste (moods, genres, vocals or
  not, favourite tracks, what they disliked) and `## general`. **Taste lives there, not in this
  skill.** If the section is empty, ask two quick questions the first time (what kind of music
  they like under family videos; instrumental only or vocals OK) and save the answers as bullets.
  The template of what is worth remembering: `reference/taste-template.md`.
- Music folder: `settings.py get paths.music_dir` (exit 4 = unset: ask where they keep music they
  may use, suggest e.g. `~/Music/Montage`, save it).
- Rights, every time (details: `reference/music-sources.md`):
  - **Published** videos (YouTube, social, anything public) need music licensed for it: the
    YouTube Audio Library, Creative Commons tracks with their credit line, tracks bought with a
    licence, or the user's own music. Never commercial songs pulled from the internet.
  - **Private** family videos: still use music the user has the rights to. If they bring their
    own files, take their word for it and note the source.
  - `yt-dlp` (if installed) is only for tracks the user may download: their own uploads, CC
    music, libraries that allow it. Say so plainly when they ask to "just rip a song from YouTube":
    it breaks YouTube's terms, and a published video gets claimed or blocked.

## Steps

1. **Score plan first, downloads second.** From home-video's `work/story.md`: group the chapters
   into the story's 2-3 mood arcs (e.g. "arrival, curious" -> "adventure days, upbeat" -> "last
   evening, warm"). One cue per arc. A single track over five minutes reads generic; a song per
   chapter is too many. Change the song only where the mood really turns.
2. **Candidates.** `find_music.py` lists what the user has. Propose two tracks per arc that match
   the mood and their taste (instrumental by default, unless preferences say otherwise; mood over
   fame). Adjacent cues should differ in energy or instruments. Missing a mood? Point them to a
   library they can download from themselves (`reference/music-sources.md`).
3. **Samples before the build.** For each part being scored, `sample.py` two candidates of exactly
   the stretch that would play, loudness-matched, into `work/music-samples/`, with a short list:
   part, time range, what is on screen, the mood, one line per candidate. Build after they pick.
   Parts nobody flagged keep their song.
4. **Analyse** each chosen track (`analyze.py`; make_draft does it automatically into
   `work/music/`). `interval_cv` <= 0.06 means the detected beats are steady; higher (rubato,
   quiet intros) means use the uniform `grid`. A half or double tempo reading does not matter:
   cuts are sized in seconds and only snap to beats.
5. **Place each cue** (the craft, `reference/craft.md`) and write it into the section in
   `work/picks.json`: `in_s` (or `end_at`), `lufs`, `fade_in`, `fade_out`.
   - Start at the **entry**: skip count-ins and long intros, begin where the band or the riff
     arrives (`entries` in the analysis, or the `--profile` jump marked ENTRY).
   - **Aim a hit at a shot**: `in_s = hit_time - (seconds of cuts before that shot)`, then check the
     cut list after the walk (a hit 0-3 frames after the visual event is right; early is worse).
   - **End naturally**: `end_at` = the track second where the music has died (`ends_at`), so the
     song's own ending lands on the last shot instead of a fade over a song still going.
   - A vocal cue: put the section on the line you want heard (the chorus, not the pre-chorus);
     `tools/transcribe.py TRACK` gives word times if a transcription engine is set up.
6. **Levels.** Cues default to -20 LUFS (`music_lufs`) under a master of -16 LUFS, over the clips'
   own sound at -21 dB RMS: the waves, the laughter and the wind stay audible. Keep quieter moods a
   few LU under fun ones, and adjacent cues within ~3 LU unless it is a deliberate smash cut.
   Ducking (the music dipping under a voice) only under a spoken line worth hearing, about 6 dB,
   never shorter than ~1.2 s; laughs and splashes sit on top without it.

## Hard rules

- Only music the user has the rights to; licensed or CC music for anything published. Log the source
  (`pull.py` writes `SOURCES.tsv`; ask the user for library downloads' licence lines and keep them
  beside the tracks).
- Never put pulled or downloaded tracks in the repo.
- Never upload anything. Install nothing (librosa, yt-dlp) without a yes: both are optional.

## What the user can customize

Their taste and default moods (`## montage-music` in preferences), the default cue loudness
(`music_lufs` in picks.json) and master loudness (`target_lufs` in the project's
`work/project.json`), and how many songs a video gets. Craft details: `reference/craft.md`.
