# Triage files (all in the work folder W)

Read this only when a script's output needs debugging or a plan needs a hand edit.

## inventory.json (inventory.py)

```json
{"input_dir": "...", "work_dir": "...", "gap_hours": 3, "exiftool": true,
 "destinations": {"projects_dir": "...", "home_videos_dir": "...", "broll_library_dir": "...", "trash_dir": "..."},
 "projects": [{"name": "garden-build", "modified": "2025-06-02", "footage_folders": ["broll-1"]}],
 "units": [{"id": "U01", "name": "2025-06-01_camera-a_card1", "folder": "card1", "device": "Camera A",
            "first": "2025-06-01T09:00:00", "last": "...", "counts": {"video": 4, "photo": 0, "audio": 0},
            "bytes": 123, "minutes": 3.5, "time_sources": ["metadata"],
            "files": [{"id": "f0001", "path": "/abs/clip.mp4", "rel": "card1/clip.mp4", "kind": "video",
                       "bytes": 1, "duration": 6.0, "width": 3840, "height": 2160, "fps": 29.97,
                       "has_audio": true, "capture_time": "2025-06-01T09:00:00", "time_source": "metadata",
                       "device": "Camera A", "sidecars": ["clip.xml"], "top_folder": "card1"}]}],
 "skipped": [{"path": "...", "reason": "not a media file (left in place)"}],
 "totals": {"files": 7, "bytes": 1, "video": 6, "photo": 1, "audio": 0}}
```

`time_source`: `file-name` (most reliable), `metadata`, or `file-date` (the
file's modified time: a copy may have reset it, treat the date as a guess).

## Verdicts (written by footage-classifier agents)

See the schema in `.claude/agents/footage-classifier.md`.

## plan.json (make_plan.py, apply_decisions.py)

```json
{"input_dir": "...", "work_dir": "...", "trash_dir": "...",
 "moves": [{"key": "U01.1", "unit_id": "U01", "destination": "project", "project": "garden-build",
            "new_project": false, "folder_name": "planting-closeups", "first_date": "2025-06-01",
            "dest_dir": "/abs/Projects/garden-build/footage/planting-closeups",
            "confidence": "high", "reason": "...", "files": ["/abs/clip.mp4"], "bytes": 1}],
 "needs_decision": [{"key": "U04", "unit_id": "U04", "files": ["..."], "first_date": "...", "bytes": 1,
                     "suggestion": "home-videos", "project": null, "folder_name": "...",
                     "notes": "why it is unsure", "confidence": "low"}],
 "unclassified": [],
 "content": {"/abs/clip.mp4": "what the classifier saw in it"},
 "problems": []}
```

Destination folders:

| destination | folder |
|---|---|
| project | `<projects_dir>/<project>/<project_layout.footage>/<folder_name>` |
| home-videos | `<home_videos_dir>/<YYYY-MM-DD>-<folder_name>` |
| broll-library | `<broll_library_dir>/footage/<folder_name>` |
| trash | `<trash_dir>/<folder_name>` |

`plan.json.approved` holds the fingerprint `move.py --approve` recorded;
`moves.log.jsonl` one line per moved file (`--undo` reads it).
