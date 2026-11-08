# Folder layout

Skills find your footage and put drafts, finals and archives in the right
place because every project follows the same layout. You choose the folders
once (in `/setup`); the defaults below work well.

## The big picture

```
<projects folder>/               paths.projects_dir  - one folder per video
  phone-case-review/
  kitchen-tour/
<inbox>/                         paths.inbox_dir     - new imports, before sorting
<archive>/                       paths.archive_dir   - finished projects (local, external drive or NAS)
<finals>/                        paths.finals_dir    - optional: every finished video in one place
<b-roll library>/                paths.broll_library_dir - reusable footage, searchable
<home videos>/                   paths.home_videos_dir   - optional: family, trips, pets
<music>/                         paths.music_dir         - optional: music you have rights to
```

All of them are optional until a skill needs one; then it asks once.

## Inside a project

Created by the `new-project` skill from settings `project_layout`:

```
phone-case-review/
  project.json        name, date, and the DaVinci Resolve project that goes with it
  footage/            camera originals - never edited in place
    a-roll.mp4
    a-roll.transcript.json     sidecar: travels with its clip
    closeup-01.mov
  audio/              separate mic recordings, music, voiceover
  graphics/           logos, screenshots, titles, thumbnails
  output/             finals
    drafts/           draft renders for review
  work/               scratch files skills make; safe to delete when archiving
```

Rename any of these in settings (`project_layout.footage` = `"01 Footage"`
etc.; `docs/settings.md`). Keep every part pointing somewhere: skills use all
six.

## Why it matters

- **Originals stay untouched.** Skills read from `footage/` and write
  elsewhere, so a mistake never costs you a recording.
- **Drafts never mix with finals.** Reviews look at drafts; finals are only
  in the finals folder.
- **Sidecars travel with their clip.** A transcript (`<clip>.transcript.json`)
  or other `<clip>.*` file sits next to the clip. Anything that moves a clip
  moves its sidecars too, so nothing is transcribed twice.
- **Archiving is safe and quick.** `work/` and drafts are known to be
  regenerable, so the archive skill can clean them up and keep what matters.
- **Resolve stays linked.** DaVinci Resolve links to files where they are;
  importing from the project's folders (not from a camera card or the
  Downloads folder) keeps those links working.

## The life of a video

1. **Import**: camera cards and phone dumps go to the inbox.
2. **Sort**: the footage-triage skill proposes where each clip goes (a
   project, home videos, the b-roll library, or the trash) and moves them on
   your yes.
3. **Edit**: drafts appear in `output/drafts/`, finals in `output/`.
4. **Release**: the youtube-release skill writes the title, description and
   chapters, plus a paste sheet you follow to upload in YouTube Studio.
5. **Archive**: the archive-project skill moves the finished project to the
   archive (lean: finals + reusable b-roll; keep: everything) after showing
   you the list.

## Big footage and several drives

- The projects folder can be on an external SSD: set `paths.projects_dir`
  to it. Skills check the drive is connected before writing and never create
  a stand-in folder when it isn't.
- Archives and libraries are a good fit for a NAS or a big external drive
  (`docs/nas.md`).
- Regenerable caches (contact sheets, analysis) go to `paths.cache_dir`
  (default `user/cache/` in this repo). Delete them any time.
