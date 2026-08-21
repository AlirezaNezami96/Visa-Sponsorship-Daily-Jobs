"""
Convenience entry point for running the Job Acquisition Engine FastAPI server.
Can be executed from inside engine/ or from the project root.
"""
import os
import sys
from pathlib import Path

# Ensure both repo root and engine directory are on sys.path
engine_dir = Path(__file__).resolve().parent
repo_root = engine_dir.parent

for p in (str(repo_root), str(engine_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    reload = os.environ.get("RELOAD", "true").lower() in ("true", "1", "yes")

    print(f"🚀 Launching Job Acquisition Engine on http://{host}:{port}")
    # Determine the import target based on current working directory
    target = "api.main:app" if (Path.cwd() == engine_dir or Path("api/main.py").exists()) else "engine.api.main:app"
    uvicorn.run(
        target,
        host=host,
        port=port,
        reload=reload,
    )
