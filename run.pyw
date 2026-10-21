"""Entry point. pythonw run.pyw (no console) or python run.pyw (with console logs)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from organiser.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
