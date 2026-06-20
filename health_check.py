"""
Health check for the scraper module: verifies `worker.py` imports cleanly
and critical env variables are present.
"""
import os
import sys
import py_compile
from pathlib import Path

print("Checking environment and importing worker module...")

# Report missing critical env vars (but continue to check imports)
missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY") if not os.environ.get(k)]
if missing:
    print("Warning: missing env vars:", ", ".join(missing))

# Ensure current folder is on sys.path so we can import worker.py
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

print("Project folder added to sys.path:", root)

try:
    # Quick compile check for syntax errors before import
    py_compile.compile(str(root / "worker.py"), doraise=True)
    import worker  # noqa: F401
    print("Import succeeded: worker module loaded")
    sys.exit(0)
except py_compile.PyCompileError as pce:
    print("Syntax error in worker.py:", pce)
    sys.exit(3)
except Exception as e:
    print("Import failed:", e)
    sys.exit(2)
