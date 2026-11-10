"""Local launcher; credentials stay in ignored runtime files."""
import os
import secrets
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
runtime=root/".runtime"
runtime.mkdir(exist_ok=True)
keyfile=runtime/"service.key"
if not keyfile.exists():
    keyfile.write_text(secrets.token_urlsafe(48),encoding="utf-8")
os.environ.setdefault("FLOWSTATE_API_KEY",keyfile.read_text(encoding="utf-8").strip())
if __name__=="__main__":
    import uvicorn
    uvicorn.run("backend.app:app",host=os.getenv("FLOWSTATE_HOST","127.0.0.1"),port=int(os.getenv("FLOWSTATE_PORT","8000")),log_level="info")
