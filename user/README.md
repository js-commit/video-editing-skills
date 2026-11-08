# user/

Your own setup lives here and is never committed (see `.gitignore`):

- `settings.json` — where your projects, archive, b-roll library and music live,
  which editor and transcription engine you use. Created by the `setup` skill
  from `settings.example.json`. Edit by hand or ask Claude ("change my archive
  folder to …"). Keys are explained in `docs/settings.md`.
- `preferences.md` — your standing preferences, one heading per skill. Claude
  adds to it when you correct something ("cuts are too tight", "always 1080p
  drafts"). Start from `preferences.example.md` or let it grow on its own.
- `cache/` — regenerable working files (safe to delete).
