from __future__ import annotations

"""
Черновой скрипт для простановки перекрёстных ссылок в markdown-файлах.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SECTION_DIR = ROOT / "WEB" / "ya_i_cifrovoy_mir"
CONCEPTS_FILE = ROOT / "WORK" / "ya_i_cifrovoy_mir" / "concepts.json"


def load_concepts() -> list[dict]:
    data = json.loads(CONCEPTS_FILE.read_text(encoding="utf-8"))
    return data["articles"]


def should_skip_line(line: str) -> bool:
    return line.strip().startswith("#") or line.strip().startswith("```")


def insert_link_once(text: str, phrase: str, target: str) -> str:
    pattern = re.compile(rf"\b({re.escape(phrase)})\b", flags=re.IGNORECASE)

    def replacer(match: re.Match[str]) -> str:
        found = match.group(1)
        return f"[{found}]({target})"

    return pattern.sub(replacer, text, count=1)


def process_file(md_path: Path, concepts: list[dict]) -> None:
    original = md_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    updated_lines = []
    for line in lines:
        if should_skip_line(line):
            updated_lines.append(line)
            continue
        new_line = line
        for concept in concepts:
            title = concept["title"]
            target = "/" + concept["web_path"].replace("\", "/")
            if md_path.as_posix().endswith(concept["web_path"]):
                continue
            if f"]({target})" in new_line:
                continue
            new_line = insert_link_once(new_line, title, target)
        updated_lines.append(new_line)
    md_path.write_text("
".join(updated_lines), encoding="utf-8")


def main() -> None:
    concepts = load_concepts()
    for md_file in SECTION_DIR.rglob("*.md"):
        process_file(md_file, concepts)
    print("Готово: черновые ссылки проставлены.")


if __name__ == "__main__":
    main()
