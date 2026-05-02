"""Allow `python -m opspilot` to run the CLI."""

from .cli import app

if __name__ == "__main__":
    app()
