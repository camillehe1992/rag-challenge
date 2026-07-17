from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


LINK_RE = re.compile(r"!?(\[[^\]]*\])\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(\s+#+\s*)?$", re.MULTILINE)


@dataclass(frozen=True)
class BrokenLink:
    source_file: Path
    target: str
    reason: str


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "tel:"))


def slugify_heading(text: str) -> str:
    cleaned = text.lower()
    cleaned = "".join(" " if ch.isspace() else ch for ch in cleaned).strip()
    cleaned = re.sub(r"[^\w\- ]", "", cleaned, flags=re.UNICODE)
    return cleaned.replace(" ", "-").strip("-")


def extract_anchors(md_text: str) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}

    for match in HEADING_RE.finditer(md_text):
        heading_text = (match.group(2) or "").strip()
        if not heading_text:
            continue
        base = slugify_heading(heading_text)
        if not base:
            continue
        count = seen.get(base, 0)
        if count == 0:
            anchors.add(base)
        else:
            anchors.add(f"{base}-{count}")
        seen[base] = count + 1
    return anchors


def parse_target(raw_target: str) -> tuple[str, str | None]:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target:
        return "", None
    if "#" in target:
        path_part, anchor = target.split("#", 1)
        return path_part.strip(), (anchor.strip() or None)
    return target, None


def iter_markdown_files(repo_root: Path) -> list[Path]:
    files = [repo_root / "README.md"]
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        files.extend(sorted(docs_dir.rglob("*.md")))
    return [fp for fp in files if fp.exists()]


def check_links(repo_root: Path, files: list[Path]) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    anchor_cache: dict[Path, set[str]] = {}

    for fp in files:
        text = fp.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw_target = match.group(2).strip()
            if not raw_target or is_external(raw_target):
                continue

            target_path, anchor = parse_target(raw_target)

            if target_path.startswith("/"):
                broken.append(
                    BrokenLink(source_file=fp, target=raw_target, reason="absolute path")
                )
                continue

            if not target_path:
                resolved = fp.resolve()
            else:
                resolved = (fp.parent / target_path).resolve()

            try:
                resolved.relative_to(repo_root.resolve())
            except Exception:
                broken.append(
                    BrokenLink(source_file=fp, target=raw_target, reason="escapes repo")
                )
                continue

            if not resolved.exists():
                broken.append(BrokenLink(source_file=fp, target=raw_target, reason="missing"))
                continue

            if anchor:
                if resolved not in anchor_cache:
                    anchor_cache[resolved] = extract_anchors(
                        resolved.read_text(encoding="utf-8")
                    )
                if anchor not in anchor_cache[resolved]:
                    broken.append(
                        BrokenLink(
                            source_file=fp,
                            target=raw_target,
                            reason="missing anchor",
                        )
                    )

    return broken


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    files = iter_markdown_files(repo_root)
    broken = check_links(repo_root=repo_root, files=files)
    if not broken:
        print("OK: all relative markdown links exist.")
        return 0

    print("BROKEN LINKS:")
    for item in broken:
        print(
            f"- {item.source_file.relative_to(repo_root)} -> {item.target} ({item.reason})"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())

