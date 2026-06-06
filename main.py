"""mini_game — entry point cho CLI tự động chơi game Android.

File này CỐ TÌNH ngắn. Mọi business logic + UI thực sự nằm trong
``cli/`` và ``core/``. Đây chỉ là entry để ``python main.py`` hoạt động.

Kiến trúc:
    cli/                    PRESENTATION (giao diện)
        parser.py           argparse build + dispatch
        commands/           1 file / subcommand
        prompts.py          input helper + wizard tương tác
        logging_setup.py    cấu hình logging
        paths.py            đường dẫn project chung
    core/                   DOMAIN + APPLICATION (logic)
        bot/                state-machine bot (RoK gather)
        fleet.py            multi-device orchestrator
        config_io.py        đọc/ghi devices.yaml
        device.py, ocr.py, store/, runner.py, scenario.py
"""
from __future__ import annotations

import os
import sys

# Set environment variable to bypass OpenMP duplicate runtime conflicts in OpenCV/PaddlePaddle
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Bypass PaddleX's runtime dependency checks to prevent DependencyError under PyInstaller EXE
try:
    import importlib.metadata
    import importlib.util
    
    orig_metadata = importlib.metadata.metadata
    orig_requires = importlib.metadata.requires
    orig_version = importlib.metadata.version
    
    def patched_metadata(distribution_name):
        try:
            return orig_metadata(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            if distribution_name == "paddlex":
                class DummyMetadata:
                    def get_all(self, name, default=None):
                        if name == "Provides-Extra":
                            return ["ocr", "ocr-core"]
                        return default
                return DummyMetadata()
            raise
            
    def patched_requires(distribution_name):
        try:
            return orig_requires(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            if distribution_name == "paddlex":
                return []
            raise
 
    def patched_version(distribution_name):
        try:
            return orig_version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            # Map distribution name to python import name
            import_name_map = {
                "opencv-contrib-python": "cv2",
                "opencv-python": "cv2",
                "paddlex": "paddlex",
                "paddleocr": "paddleocr",
                "pypdfium2": "pypdfium2",
                "shapely": "shapely",
                "pyclipper": "pyclipper",
                "paddlepaddle": "paddle",
                "paddle-custom-device": "paddle_custom_device",
                "ultra-infer": "ultra_infer",
                "fastdeploy": "fastdeploy",
            }
            import_name = import_name_map.get(distribution_name, distribution_name)
            try:
                if importlib.util.find_spec(import_name) is not None:
                    return "99.0.0"
            except Exception:
                pass
            raise
            
    importlib.metadata.metadata = patched_metadata
    importlib.metadata.requires = patched_requires
    importlib.metadata.version = patched_version

    # Monkeypatch paddlex deps functions to bypass version/package existence checks
    import paddlex.utils.deps as deps
    deps.is_extra_available = lambda extra: True
    deps.is_dep_available = lambda dep, check_version=False: True
    deps.require_extra = lambda extra, **kwargs: None
    deps.require_deps = lambda *deps, **kwargs: None

    # Monkeypatch repo_manager.initialize in both namespaces to prevent RuntimeError on duplicate runs
    import paddlex.repo_manager.core as repo_manager_core
    repo_manager_core.initialize = lambda *args, **kwargs: None
    
    import paddlex.repo_manager as repo_manager
    repo_manager.initialize = lambda *args, **kwargs: None
except Exception as e:
    import traceback
    print("DEBUG: Monkeypatch initialization failed:")
    traceback.print_exc()

# Reconfigure stdout and stderr to use UTF-8 to prevent UnicodeEncodeError on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from cli import run

if __name__ == "__main__":
    sys.exit(run())
