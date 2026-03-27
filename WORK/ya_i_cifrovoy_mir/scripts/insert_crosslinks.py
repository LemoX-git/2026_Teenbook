from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
SECTION_DIR = ROOT / "WEB" / "ya_i_cifrovoy_mir"
CONCEPTS_FILE = ROOT / "WORK" / "ya_i_cifrovoy_mir" / "concepts.json"
FOOTER_HEADINGS = {
    "## связанные статьи",
    "## полезные понятия из wikidata",
    "## источники данных",
    "## навигация по разделу",
}
PROTECTED_RE = re.compile(r"(`[^`]*`|!?\[[^\]]+\]\([^\)]+\)|<https?://[^>]+>)")


def load_articles() -> list[dict]:
    data = json.loads(CONCEPTS_FILE.read_text(encoding="utf-8"))
    articles = data.get("articles", [])
    return sorted(articles, key=lambda item: len(item.get("title", "")), reverse=True)


def normalize_heading(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def should_skip_line(line: str, in_code_block: bool) -> tuple[bool, bool]:
    stripped = line.strip()
    if stripped.startswith("```"):
        return True, not in_code_block
    if in_code_block:
        return True, in_code_block
    if stripped.startswith("#") or stripped.startswith(">"):
        return True, in_code_block
    return False, in_code_block


def title_to_target_map() -> dict[str, Path]:
    return {article["title"]: ROOT / article["web_path"] for article in load_articles()}


def build_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    return re.compile(rf"(?<![\w/\-])({escaped})(?![\w/\-])", flags=re.IGNORECASE)


def replace_in_plain_text(text: str, phrase: str, target: str) -> tuple[str, bool]:
    pattern = build_pattern(phrase)

    def repl(match: re.Match[str]) -> str:
        return f"[{match.group(1)}]({target})"

    updated, count = pattern.subn(repl, text, count=1)
    return updated, count > 0


def apply_link_safely(line: str, phrase: str, target: str) -> tuple[str, bool]:
    parts = PROTECTED_RE.split(line)
    changed = False
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            continue
        replaced, local_changed = replace_in_plain_text(part, phrase, target)
        if local_changed:
            parts[idx] = replaced
            changed = True
            break
    return "".join(parts), changed


def process_file(md_path: Path, mapping: dict[str, Path]) -> None:
    original = md_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    updated_lines: list[str] = []
    in_code_block = False
    in_footer = False
    linked_titles: set[str] = set()

    for line in lines:
        if normalize_heading(line) in FOOTER_HEADINGS:
            in_footer = True

        skip_line, in_code_block = should_skip_line(line, in_code_block)
        if skip_line or in_footer:
            updated_lines.append(line)
            continue

        new_line = line
        for title, target_path in mapping.items():
            if title in linked_titles:
                continue
            if target_path.resolve() == md_path.resolve():
                continue

            rel_link = os.path.relpath(target_path, start=md_path.parent).replace("\\", "/")
            if f"]({rel_link})" in new_line:
                linked_titles.add(title)
                continue

            updated, changed = apply_link_safely(new_line, title, rel_link)
            if changed:
                new_line = updated
                linked_titles.add(title)

        updated_lines.append(new_line)

    md_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def iter_markdown_files() -> Iterable[Path]:
    yield from SECTION_DIR.rglob("*.md")


def main() -> None:
    mapping = title_to_target_map()
    for md_file in iter_markdown_files():
        process_file(md_file, mapping)
    print("Готово: перекрёстные ссылки проставлены в основных текстах статей.")


if __name__ == "__main__":
    main()
