"""Where in a video to look: the one definition of triage sampling density.

Shared by vlm-describe (frames pulled from a video input) and by the skills
that render contact sheets, so they can never disagree about how many frames a
clip gets or when they are.

  < 15 s        4 frames  (2x2)
  15 s - 2 min  6 frames  (3x2)
  2 - 8 min    12 frames  (4x3)
  > 8 min      16 frames  (4x4, cap)

This is TRIAGE density: enough to answer "what is this clip", not enough to
pick a moment. Callers wanting a moment pass their own count or timestamps.
"""

# lead-in before the first frame and trailing margin the last one keeps clear
# of, so a clip's fade-in / hand reaching for the record button is skipped
FIRST_AT_S = 0.3
TAIL_MARGIN_S = 0.6


def frame_count(duration_s):
    if not duration_s or duration_s < 15:
        return 4
    if duration_s < 120:
        return 6
    if duration_s < 480:
        return 12
    return 16


def grid(n):
    """(cols, rows) of a contact sheet holding n tiles."""
    cols = 2 if n <= 4 else 3 if n <= 6 else 4
    return cols, -(-n // cols)


def frame_times(duration_s, n):
    """n timestamps evenly spread over the clip, seconds, 2 decimals."""
    dur = max(duration_s or 1.0, 1.0)
    if n == 1:
        return [round(dur / 2, 2)]
    if dur <= 1.5:
        return [0.1] * n
    span = dur - FIRST_AT_S - TAIL_MARGIN_S
    return [round(FIRST_AT_S + i * span / (n - 1), 2) for i in range(n)]
