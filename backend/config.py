import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("FLOWSTATE_DATA", str(ROOT / "data")))
DATA.mkdir(parents=True, exist_ok=True)
FRAMES = DATA / "frames"
FRAMES.mkdir(exist_ok=True)
MODEL = DATA / "yolox_tiny.onnx"
API_KEY = os.getenv("FLOWSTATE_API_KEY", "")
if os.getenv("FLOWSTATE_REQUIRE_API_KEY") == "1" and len(API_KEY.strip()) < 32:
    raise RuntimeError("FLOWSTATE_API_KEY must contain at least 32 characters for production.")
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
