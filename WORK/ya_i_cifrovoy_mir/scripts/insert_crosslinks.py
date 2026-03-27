from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SECTION_DIR = ROOT / "WEB" / "ya_i_cifrovoy_mir"
CONCEPTS_FILE = ROOT / "WORK" / "ya_i_cifrovoy_mir" / "concepts.json"


def load_articles() -> list[dict]:
    data = json.loads(CONCEPTS_FILE.read_text(encoding="utf-8"))
    return data["articles"]


def should_skip_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith("```") or stripped.startswith(">")


def title_to_target_map() -> dict[str, Path]:
    return {article["title"]: ROOT / article["web_path"] for article in load_articles()}


def link_text_once(text: str, phrase: str, target: str) -> str:
    pattern = re.compile(rf"(?<!\[)({re.escape(phrase)})", flags=re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        return f"[{match.group(1)}]({target})"

    return pattern.sub(repl, text, count=1)


def process_file(md_path: Path, mapping: dict[str, Path]) -> None:
    original = md_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    updated_lines: list[str] = []

    for line in lines:
        if should_skip_line(line):
            updated_lines.append(line)
            continue

        new_line = line
        for title, target_path in mapping.items():
            if target_path.resolve() == md_path.resolve():
                continue

            rel_link = __import__("os").path.relpath(target_path, start=md_path.parent).replace("\\", "/")
            if f"]({rel_link})" in new_line:
                continue

            new_line = link_text_once(new_line, title, rel_link)

        updated_lines.append(new_line)

    md_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main() -> None:
    mapping = title_to_target_map()
    for md_file in SECTION_DIR.rglob("*.md"):
        process_file(md_file, mapping)
    print("Готово: перекрёстные ссылки проставлены в черновом режиме.")


if __name__ == "__main__":
    main()
