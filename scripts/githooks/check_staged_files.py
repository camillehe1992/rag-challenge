import subprocess
import sys

from protected_files import is_protected_path


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    blocked = [path for path in staged_files() if is_protected_path(path)]
    if not blocked:
        return 0

    print("The following files should not be committed:", file=sys.stderr)
    for path in blocked:
        print(f"  - {path}", file=sys.stderr)
    print("Unstage them with: git restore --staged <path>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
