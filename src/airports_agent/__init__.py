import subprocess
import sys
from pathlib import Path


def main() -> None:
    ui_path = Path(__file__).parent / "agent" / "ui.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ui_path)])


if __name__ == "__main__":
    main()
