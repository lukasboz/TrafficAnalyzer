"""Production entrypoint: persistent volume initialization, then drop root privileges."""
import os
from pathlib import Path


def main():
    if len(os.getenv("FLOWSTATE_API_KEY", "").strip()) < 32:
        raise SystemExit("Set FLOWSTATE_API_KEY to a random secret with at least 32 characters.")
    data = Path(os.getenv("FLOWSTATE_DATA", "/data")).resolve()
    # The image owns /data. Never recursively change ownership on an arbitrary mount.
    if data != Path("/data"):
        raise SystemExit("The container's persistent data volume must be mounted at /data.")
    data.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(data, 10001, 10001)
        for child in [data / "frames", data / "yolox_tiny.onnx", data / "flowstate.sqlite3", data / "flowstate.sqlite3-wal", data / "flowstate.sqlite3-shm"]:
            if child.exists() and not child.is_symlink():
                os.chown(child, 10001, 10001)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    port = int(os.getenv("PORT", os.getenv("FLOWSTATE_PORT", "8000")))
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535.")
    os.execvp("uvicorn", ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", str(port), "--workers", "1"])


if __name__ == "__main__":
    main()
