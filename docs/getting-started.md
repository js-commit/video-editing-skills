# Getting started

This toolkit is a set of **skills** for Claude Code: instructions and small
scripts that let Claude edit video with the tools on your computer. You talk
to Claude in plain language ("draft this a-roll", "make a project for my
next video") and it does the work, explains what it is doing, and asks
before anything risky.

You need about 15 minutes for the steps below.

## 1. What you need

- **A computer**: macOS works best (everything is tested there). The
  ffmpeg-based skills are written to work on Windows and Linux too, but are
  not tested there yet; reports and fixes are welcome.
- **Claude Code** with a Claude subscription or API account (step 2).
- **Python 3.9 or newer**. macOS: open Terminal and run `python3 --version`;
  if macOS offers to install the command line developer tools, accept
  (that also brings git). Windows: install Python from python.org or
  `winget install Python.Python.3.12` and tick "Add python.exe to PATH".
  Linux: usually already there.
- **ffmpeg**, the free video tool everything uses. The setup step checks for
  it and gives you the exact install command (macOS with Homebrew:
  `brew install ffmpeg`; Windows: `winget install --id Gyan.FFmpeg`; Linux:
  `sudo apt install ffmpeg`).
- **Optional: DaVinci Resolve.** The free version works with these skills for
  importing timelines by hand; **DaVinci Resolve Studio** (paid) lets Claude
  build and change timelines for you. No Resolve at all is fine too: drafts
  are rendered with ffmpeg.

## 2. Install Claude Code

Follow Anthropic's official Claude Code install instructions for your system
(search for "Claude Code install"). At the time of writing:

```sh
# macOS / Linux
curl -fsSL https://claude.ai/install.sh | bash
# Windows (PowerShell)
irm https://claude.ai/install.ps1 | iex
```

Run `claude` once in a terminal and sign in.

## 3. Get this toolkit

```sh
git clone https://github.com/js-commit/video-editing-skills video-editing-skills
cd video-editing-skills
```

(No git? Download the ZIP from the repository page and unzip it.)

Put it anywhere you like; it doesn't need to be next to your videos. Your own
settings and preferences stay in its `user/` folder and are never uploaded
or committed.

## 4. Open Claude in the folder

```sh
cd video-editing-skills
claude
```

Claude Code loads the skills from this folder. The first time, Claude
notices nothing is set up and offers the setup.

## 5. Run setup

Type `/setup` (or say "set me up"). Claude will:

1. check what your computer has (ffmpeg, DaVinci Resolve, transcription
   options) without changing anything,
2. ask a few short questions, all skippable: what you make, how much editing
   you've done, your editing app, where your projects should live, whether
   you have a NAS (network drive), how to transcribe, how you want to review
   drafts, the privacy you usually upload with,
3. offer to install anything missing (only with your yes, one tool at a time),
4. save your answers to `user/settings.json` and start
   `user/preferences.md`.

You can stop at any point and run `/setup` again later; it remembers your
answers and only asks what's missing.

**API keys** (only if you choose ElevenLabs for transcription): set them in your own terminal, never in the chat or in this folder.

```sh
# macOS (zsh)
echo 'export ELEVENLABS_API_KEY="paste-your-key"' >> ~/.zprofile   # then open a new terminal
# Linux (bash): the same line into ~/.bashrc
# Windows (PowerShell)
setx ELEVENLABS_API_KEY "paste-your-key"                         # then open a new terminal
```

Restart Claude Code from the new terminal so it sees the key. (The variable
name for each engine is shown by the setup check and in `docs/transcription.md`.)

## 6. Your first a-roll draft

**A-roll** is the main footage of you talking to the camera. A first cut
removes the retakes, ums and long pauses.

1. Record (or pick) a talking-head clip, a few minutes long.
2. Optional: say "create a project called test video" and copy the clip into
   its footage folder.
3. Tell Claude: `draft this a-roll: /full/path/to/clip.mp4`
   (drag the file into the terminal to paste its path).
4. Claude transcribes it (once; the transcript is saved next to the clip),
   decides what to cut, and makes:
   - a quick preview video in the project's drafts folder (automatic
     without Resolve; Resolve users ask for it: "render a preview too"),
   - timeline files for DaVinci Resolve (with Studio, it can build the
     timeline for you; with the free version, import it via
     File > Import > Timeline).
5. Watch the preview. Tell Claude what to change ("you cut my joke at 1:10",
   "leave more air between sentences"). Lasting preferences are remembered
   for next time.

## 7. What next

- `docs/keyboard-shortcuts.md`: the keys worth learning first, in DaVinci
  Resolve, EditReview and the companion apps.
- Ask the editing coach anything: "what's a J-cut?", "how do I color correct
  in Resolve?", "look at this clip and tell me how to film it better".
- `docs/folder-layout.md`: how projects, the inbox, archive and b-roll
  library fit together.
- `docs/settings.md`: every setting explained.
- Make it yours: "from now on, always render drafts at 720p", or "change how
  the thumbnail skill picks frames". The `customize` skill edits this copy for
  you, with a backup and an undo.

## Troubleshooting

- **"python3: command not found"** (Windows): use `python` instead, or
  install Python as above. If `python3` opens the Microsoft Store, install
  Python from python.org and reopen the terminal.
- **"ffmpeg is not installed"**: run the install command shown, then open a
  new terminal (and restart Claude Code) so it is found.
- **A skill says a setting is not set**: answer its question; it saves the
  answer and continues. Or run `/setup`.
- **DaVinci Resolve automation doesn't connect**: it needs Studio, Resolve
  running, and DaVinci Resolve > Preferences > System > General > "External
  scripting using" set to Local (restart Resolve after changing it).
