"""Shared test configuration — adds bluemarlin/ root to sys.path."""
import sys
import os

# Add bluemarlin/ (parent of tests/) to sys.path so package imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
