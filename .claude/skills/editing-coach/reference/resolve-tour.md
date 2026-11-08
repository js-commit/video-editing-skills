# DaVinci Resolve tour

DaVinci Resolve comes in a free version and a paid **Studio** version. Both
edit, color, mix and render. Studio adds external scripting (which these
skills use for automation), hardware-accelerated H.264/H.265 encoding on more
systems, higher resolutions and frame rates, noise reduction and many AI
tools. Menus move between versions: check the user's version and when unsure
say "in recent versions" and show how to find it.

Keys below are macOS defaults; on Windows/Linux ⌘ = Ctrl and ⌥ = Alt.
Resolve shows each command's current shortcut next to it in the menus: that
is the source of truth, especially after customizing.

## The pages (tabs along the bottom)

| Page | What it is for |
|---|---|
| Media | Import and organize footage, sync audio, make proxies |
| Cut | A fast, simple editor for quick assemblies |
| Edit | The classic timeline editor: most editing happens here |
| Fusion | Motion graphics and compositing |
| Color | Color correction and grading with nodes |
| Fairlight | Audio mixing, effects, loudness |
| Deliver | Render (export) the timeline |

In recent versions ⇧2...⇧8 jump between pages (the order can shift when a
version adds a page; Workspace > Switch to Page lists the keys). The
Project Manager (all projects) is the house icon at the bottom right.

## Essential Edit-page shortcuts (defaults)

| Do this | Key |
|---|---|
| Play / stop | Space |
| Play backward / stop / forward (tap again = faster) | J / K / L |
| One frame back / forward | ← / → |
| One second back / forward | ⇧← / ⇧→ |
| Previous / next cut | ↑ / ↓ |
| Mark in / out | I / O |
| Clear in and out | ⌥X |
| Cut (split) at the playhead | ⌘B |
| Selection tool / Trim tool / Blade tool | A / T / B |
| Delete, leave a gap | ⌫ (Backspace) |
| Ripple delete (close the gap) | ⇧⌫ or ⌦ (forward Delete) |
| Trim clip start / end to playhead | ⇧[ / ⇧] |
| Ripple start / end to playhead | ⌘⇧[ / ⌘⇧] |
| Snapping on / off | N |
| Linked selection on / off (video + audio move together) | ⌘⇧L |
| Enable / disable clip | D |
| Add marker | M |
| Zoom timeline in / out / to fit | ⌘= / ⌘- / ⇧Z |
| Insert / overwrite edit (from the source viewer) | F9 / F10 |
| Add the standard transition | ⌘T |
| Match frame (open the source at this frame) | F |
| Retime controls (speed) | ⌘R |
| Undo / redo / save | ⌘Z / ⌘⇧Z / ⌘S |
| Import media | ⌘I |

On macOS, F-keys may need fn, or turn on "Use F1, F2, etc. keys as standard
function keys" in System Settings > Keyboard.

## Keyboard customization

DaVinci Resolve > Keyboard Customization (⌥⌘K; Windows/Linux: Ctrl+Alt+K).
- The preset menu (top right) has DaVinci Resolve plus layouts modeled on
  Adobe Premiere Pro, Final Cut Pro, Avid Media Composer and Pro Tools. The
  Premiere preset follows an older Premiere layout, so a few keys (like the
  Q/W ripple trims) may not match current Premiere: check them after
  switching, or start from the DaVinci preset and remap only the keys you
  miss (see premiere-to-resolve.md).
- Search a command by name, click its shortcut field, press the new key. A
  conflict warning shows what you'd override.
- Save as a new preset (keep the stock one untouched). The preset menu can
  also import and export presets, to move your keys to another computer.

## Projects and media management

- Projects live in a **project library** (a database), not as files next to
  your footage. Back them up: in the Project Manager, right-click a project >
  Export Project (.drp, the timeline and settings, small) or Export Project
  Archive (.dra, with media copied in, large).
- Resolve links to footage where it is; it doesn't copy it. Moving footage
  makes clips go offline (red); relink with right-click > Relink Selected
  Clips (or the relink button in the Media Pool, in recent versions).
- Keep footage in the project's footage folder before importing, so the
  links survive.
- **Proxies / optimized media**: smaller copies that edit smoothly on slower
  computers; right-click clips in the Media Pool > Generate Proxy Media (or
  Generate Optimized Media). Playback > Proxy Handling picks which plays.
  Renders always use the originals unless you change that.
- Set the timeline resolution and frame rate in File > Project Settings >
  Master Settings **before** you start editing; the frame rate can't change
  once the timeline has clips. Match your camera (e.g. 23.976, 25, 29.97).
- Save often (⌘S); turn on Project Save and Load > Live Save in Preferences >
  User for autosave.

## Render settings for YouTube (Deliver page)

1. Deliver page (rocket icon). Choose the **YouTube** preset at the top, or
   Custom Export.
2. Format MP4 or QuickTime; codec H.264 (widest support) or H.265 (smaller
   files at the same quality; good for 4K and HDR).
3. Resolution: the timeline's (e.g. 3840x2160 for 4K, 1920x1080 for HD).
   Frame rate: the timeline's (never convert here).
4. Quality: "Automatic / Best" is fine; or restrict to a bitrate. YouTube's
   recommended upload bitrates for SDR H.264: about 8 Mbps for 1080p at
   24-30 fps (12 Mbps at 48-60 fps) and 35-45 Mbps for 4K at 24-30 fps (53-68
   at 48-60 fps). Higher is fine: YouTube re-encodes everything.
5. Audio: AAC, 48 kHz, 320 kb/s stereo. Recent versions have a loudness
   normalization option in the Audio tab: target -14 LUFS for YouTube (see
   audio.md).
6. Filename and location (the project's finals folder), **Add to Render
   Queue**, then **Render All**.

For quick review drafts, a 1080p H.264 at a lower bitrate is plenty (the
resolve-export-draft skill makes these for you).

## Getting help inside Resolve

- Help > DaVinci Resolve Reference Manual: the official manual (searchable PDF).
- Help menu search (macOS) finds any menu command by name.
- Blackmagic Design's free training books and videos cover each page in depth.
