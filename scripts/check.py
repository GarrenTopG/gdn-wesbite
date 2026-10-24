from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = ["main.py", "app", "tests", "migrations"]

COMMANDS = [
    [sys.executable, "-m", "ruff", "check", *PYTHON_FILES],
    [sys.executable, "-m", "ruff", "format", "--check", *PYTHON_FILES],
    [sys.executable, "-m", "mypy"],
    [sys.executable, "-m", "unittest", "discover", "-v"],
]


def check_python_syntax() -> None:
    for root in (ROOT / "main.py", ROOT / "app", ROOT / "tests", ROOT / "migrations"):
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            if path.is_file():
                compile(path.read_text(encoding="utf-8"), str(path), "exec")


def main() -> int:
    for command in COMMANDS[:3]:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode

    try:
        check_python_syntax()
    except (OSError, SyntaxError) as error:
        print(f"Python buildability check failed: {error}", file=sys.stderr)
        return 1

    return subprocess.run(COMMANDS[3], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
