"""
Colab-friendly wrapper to run the scraper with safe Chromium flags.
Usage in Colab:
  1. Set SUPABASE_URL and SUPABASE_KEY in the notebook.
  2. Run this script to launch the worker with Colab-suitable flags.
"""
import os
import sys
import subprocess

HERE = os.path.dirname(__file__)

os.environ.setdefault("HEADLESS", "true")
os.environ.setdefault("CHROMIUM_ARGS", "--no-sandbox --disable-dev-shm-usage --disable-gpu")

if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
    print("Warning: SUPABASE_URL or SUPABASE_KEY not set. Set them before running the worker.")

worker_path = os.path.abspath(os.path.join(HERE, "worker.py"))
print("Starting worker with:")
print("  HEADLESS=", os.environ.get("HEADLESS"))
print("  CHROMIUM_ARGS=", os.environ.get("CHROMIUM_ARGS"))

subprocess.run([sys.executable, worker_path])
