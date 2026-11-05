"""
Entrypoint alias for server execution.
Allows starting the bridge seamlessly via `python server/start.py` or `python start.py`.
"""
import os
import sys
import importlib.util

# Add project root and server directory to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Dynamically load the root start.py module avoiding circular self-import
_root_start_path = os.path.join(PROJECT_ROOT, "start.py")
if os.path.exists(_root_start_path):
    _spec = importlib.util.spec_from_file_location("root_start", _root_start_path)
    if _spec and _spec.loader:
        start = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(start)
        for _attr in dir(start):
            if not _attr.startswith("__"):
                globals()[_attr] = getattr(start, _attr)

if __name__ == "__main__":
    start.main()
