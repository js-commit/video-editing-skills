"""Run every broll-brick-layer test: python3 -B tests/run_all.py
(logic tests need nothing; media tests need ffmpeg; nothing needs Resolve)."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
failed = 0
for t in ("test_logic.py", "test_media.py"):
    r = subprocess.run([sys.executable, "-B", os.path.join(HERE, t)])
    print(("ok   " if r.returncode == 0 else "FAIL ") + t)
    failed += r.returncode != 0
sys.exit(1 if failed else 0)
