import subprocess
import sys

from protected_files import is_protected_path


ZERO_SHA = "0" * 40


def git_tree_files(revision: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def pushed_revisions() -> list[str]:
    revisions: list[str] = []
    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) < 4:
            continue
        _local_ref, local_sha, _remote_ref, _remote_sha = parts[:4]
        if local_sha and local_sha != ZERO_SHA:
            revisions.append(local_sha)

    if revisions:
        return revisions

    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [result.stdout.strip()]


def main() -> int:
    blocked: dict[str, list[str]] = {}

    for revision in pushed_revisions():
        files = [path for path in git_tree_files(revision) if is_protected_path(path)]
        if files:
            blocked[revision] = files

    if not blocked:
        return 0

    print("Push blocked: protected files are present in the pushed tree.", file=sys.stderr)
    for revision, files in blocked.items():
        print(f"\nRevision {revision} contains:", file=sys.stderr)
        for path in files:
            print(f"  - {path}", file=sys.stderr)
    print("\nRemove these files from Git history before pushing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
