---
name: resolve-export-draft
description: Render the DaVinci Resolve timeline being edited to a 1080p H.264 draft MP4 in the project's drafts folder (auto-numbered <project>-draft-N.mp4) for review, entirely from the command line with DaVinci Resolve Studio; with the free version, walks the user through the Deliver page instead. Use when asked to "render a draft", "export the timeline", "make a review copy", "dump the current cut to a file" or "export so I can watch it on my phone". Publishing a release is youtube-release, not this.
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../*/scripts/*), Bash(python3 ${CLAUDE_SKILL_DIR}/../../../tools/*), Bash(ffprobe *), Read
---

# Resolve draft export

**What it makes.** A draft is a quick, smaller copy of the edit for
watching and leaving notes on (in EditReview or any player), not the final
master. This renders the whole timeline to
`<project>/<project_layout.drafts>/<project>-draft-N.mp4`: H.264 video (the
codec every device plays), AAC audio, 1080 pixels on the short side,
numbered so earlier drafts and their review notes stay untouched. Render
time is roughly a third of the timeline's length at 1080p on a recent
computer.

## Before you start

1. Read `user/preferences.md`: `## general` and `## resolve-export-draft`
   (draft size, a preset of their own, where drafts go...).
2. `python3 tools/vidkit/settings.py get editor.nle`:
   - `resolve-studio`: the script below.
   - `resolve-free`: the free version blocks external scripting. Teach the
     Deliver page steps (below).
   - `none`: no Resolve timeline to render; ffmpeg skills render their own
     drafts (aroll-draft, talking-head-ffmpeg).
3. Resolve must be running with the project open. Never launch, quit or
   switch projects on the user without asking: they may be mid-edit.

## Steps (Resolve Studio)

```
S=${CLAUDE_SKILL_DIR}/scripts/render_draft.py
python3 $S --list                       # open project, current timeline, every timeline
python3 $S [--project P] [--timeline T] # render; prints the result as JSON
```

- Before the first scripted render in a Resolve session, ask the user to open
  the Deliver page (Shift+8) and check that "Upload directly to YouTube" is
  unticked: after any YouTube preset it can stay on for the whole session,
  and the scripting API can neither see nor clear it.
- Default timeline: the project's current one (what the user last had
  open). The deliverable is the edited cut, never a b-roll supply timeline
  or anything with "backup" in its name. If unsure, `--list` and ask.
- Default folder: the drafts folder of the project most of the timeline's
  clips live in. Exit 4 means `paths.projects_dir` is unset: ask, set it,
  re-run. `--out-dir` / `--name` override.
- It checks for offline media first (exit 2 lists each clip, its track and
  time: relink in the Media page, then re-run), renders only its own job
  (the user's queued render jobs are left alone), verifies the file with
  ffprobe (length matches the timeline, has video), then removes its own
  job from the queue.
- Long timelines: run it in the background and check its output rather
  than blocking.
- If EditReview's cuts exporter is installed, `<draft>.review/cuts.json`
  (where each clip sits in the file) is written too; EditReview uses it to
  snap to cuts.
- If the result says `upload_seen`, the Deliver page's "Upload directly to"
  box was ticked: the file also went online. Tell the user straight away;
  they delete it in YouTube Studio and untick the box.

Report the file's absolute path, duration against the timeline, size, and
which timeline you picked (and why, if they did not name it).

## Free version: the Deliver page by hand

Teach it once, briefly:

1. Open the Deliver page: the rocket icon at the bottom, or Shift+8.
2. Render Settings (top left): choose the **H.264 Master** or **YouTube
   1080p** preset, or Custom with Format MP4, Codec H.264, Resolution
   1920x1080. Untick "Upload directly to..." if it is there.
3. Timeline range: "Entire Timeline" (not In/Out) in the bar above the
   timeline.
4. File: name it `<project>-draft-N`, location the project's drafts folder
   (`python3 tools/vidkit/settings.py drafts-dir <any clip of the project>`
   prints it).
5. **Add to Render Queue**, then **Render All** in the queue on the right.

Handy: Shift+4 back to the Edit page; Cmd+S / Ctrl+S saves the project;
a preset saved from Render Settings ("Save as New Preset") can be set as
`editor.draft_render_preset` for the scripted path later.

## Hard rules

- Never delete or start other render jobs (never "delete all jobs").
- Never render a backup timeline.
- Drafts go in the project's drafts folder, never next to the camera files.
- No uploads from here; a ticked upload box gets reported, not used.

## Customize

Draft size (`render.draft_height`, the short side), a render preset of the
user's own (`editor.draft_render_preset`), the drafts folder
(`project_layout.drafts`). Record lasting choices under
`## resolve-export-draft` in `user/preferences.md`.
