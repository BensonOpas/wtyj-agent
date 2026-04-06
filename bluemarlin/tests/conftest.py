"""Shared test configuration — adds bluemarlin/ root to sys.path
and points config_loader at the BlueMarlin client config for dev tests.
"""
import sys
import os

# Add bluemarlin/ (parent of tests/) to sys.path so package imports work
_BM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BM_ROOT)

# Brief 150 — BlueMarlin's client.json moved from bluemarlin/config/ to
# clients/bluemarlin/config/. Tests that use config_loader need to find it.
# Set CLIENT_CONFIG_PATH BEFORE any test module imports config_loader.
_REPO_ROOT = os.path.dirname(_BM_ROOT)
_BM_CLIENT_CONFIG = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "config", "client.json")
if os.path.exists(_BM_CLIENT_CONFIG) and "CLIENT_CONFIG_PATH" not in os.environ:
    os.environ["CLIENT_CONFIG_PATH"] = _BM_CLIENT_CONFIG
