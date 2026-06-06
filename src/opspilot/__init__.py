"""OpsPilot — AI-augmented IT ops workbench.

Stage 1 PR-1: skeleton + JSON schema validation tooling.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opspilot")
except PackageNotFoundError:  # running from a raw checkout without an install
    __version__ = "0.0.0+unknown"
