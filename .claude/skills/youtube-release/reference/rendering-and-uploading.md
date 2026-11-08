# Rendering the master in Resolve, and uploading it

## Rendering the final master in DaVinci Resolve Studio

`scripts/render_master.py` renders the current timeline at its full
resolution into the project's finals folder. It adds one render job of its
own, starts only that job, and checks the file afterwards (length, video
stream). It never clears the render queue.

Before running it:

- Open the project and the timeline that is the finished edit. Backup
  timelines are refused.
- In/out marks don't matter: the script renders the whole timeline.
- **"Upload directly to YouTube" must be off.** Resolve's YouTube render
  presets tick it, and once one has been used, Resolve can keep uploading
  every later render (even with another preset, or none) until the app
  restarts. The scripting API can neither read nor clear the box. So before
  the first scripted render of a Resolve session, ask the user to open the
  Deliver page (Shift+8) and untick it, or to restart Resolve. After each
  render the script reads Resolve's log and says loudly if an upload
  happened; then the user deletes that video in Studio.
- The scripting API cannot set the bitrate. For a specific quality, set it up
  once on the **Deliver** page (Resolve's render page, the rocket icon at the
  bottom, or Shift+8), click **...** next to the render settings > **Save as
  new preset**, and pass `--preset "<that name>"`. Save it with the YouTube
  upload box unticked. A good YouTube master: MP4, H.265 (or H.264), the
  timeline's resolution, 40-80 Mb/s for 4K, 20-40 Mb/s for 1080p, AAC
  320 kb/s audio.
- Leave **Normalize Audio** alone: `loudness.py` measures the rendered file
  and fixes it with ffmpeg afterwards. (If you prefer Resolve to do it, pick
  **Optimize to standard** > YouTube, not **Normalize to standard**: normalize
  is gain-only, stops at the peak ceiling and leaves quiet speech quiet.)
- The "Estimated file size" on the Deliver page is not reliable; judge the
  finished file.

DaVinci Resolve (free): external scripting is not available. Render on the
Deliver page by hand (whole timeline, timeline resolution) into the project's
finals folder, then hand the file to the release skill.

No Resolve: talking-head-ffmpeg's final render (`--final`), or any master the
user names.

## Uploading by hand in YouTube Studio

`metadata.py check` writes `paste-sheet.md` in the release folder: open it next
to <https://studio.youtube.com> and follow it.

1. **Create** (top right) > **Upload videos** > pick the master.
2. **Details**: paste the title and the description (the chapters are inside
   it); upload the thumbnail; answer **Audience** (made for kids or not).
   **Show more**: tags, altered content, language, category.
3. **Video elements**: end screen and cards, if wanted.
4. **Checks**: wait for the copyright check to finish.
5. **Visibility**: Unlisted for a review, Public or **Schedule** to release.

Then give Claude the video link so the release folder can record it.

## Monetization is always a Studio step

If the channel is in the YouTube Partner Program, open the video in Studio >
**Monetization** after the upload, set ads on, answer the ad-suitability
questions honestly, and **Save**.
