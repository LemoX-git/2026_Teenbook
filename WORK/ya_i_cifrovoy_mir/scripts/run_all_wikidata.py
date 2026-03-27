"""Запускает все зарегистрированные SPARQL-запросы к Wikidata и сохраняет результаты в data/.

Что делает скрипт:
1. Читает WORK/ya_i_cifrovoy_mir/scripts/query_registry.json
2. Выполняет запросы для выбранной темы или для всех тем сразу
3. Сохраняет:
   - raw JSON-ответы в data/wikidata/*.raw.json
   - упрощённые ответы в data/wikidata/*.normalized.json
   - сводный файл в data/wikidata_export.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 60
DEFAULT_DELAY = 1.0
DEFAULT_RETRIES = 3
DEFAULT_USER_AGENT = "ya-i-cifrovoy-mir-student-project/1.0 (educational use)"


@dataclass
class QueryResult:
    topic_slug: str
    topic_title: str
    query_name: str
    const_name: str
    status: str
    row_count: int = 0
    raw_file: str | None = None
    normalized_file: str | None = None
    skipped_reason: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Выполняет SPARQL-запросы к Wikidata по реестру query_registry.json"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).resolve().with_name("query_registry.json"),
        help="Путь к query_registry.json",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="Slug темы. Можно передать несколько раз: --topic moya_zavisimost --topic moi_igry",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Имя запроса из реестра: find_by_label, expand_class_tree, local_graph, reverse_graph",
    )
    parser.add_argument("--list-topics", action="store_true", help="Показать доступные темы и выйти")
    parser.add_argument("--list-queries", action="store_true", help="Показать темы и их запросы и выйти")
    parser.add_argument("--dry-run", action="store_true", help="Ничего не выполнять, только показать план")
    parser.add_argument("--force", action="store_true", help="Перезаписать уже существующие результаты")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Пауза между запросами в секундах")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Таймаут HTTP-запроса")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Количество повторов при временной ошибке")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent для запросов к Wikidata")
    return parser.parse_args()


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден registry-файл: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def flatten_bindings(raw_response: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bindings = raw_response.get("results", {}).get("bindings", [])
    for binding in bindings:
        row: dict[str, Any] = {}
        for field, payload in binding.items():
            value = payload.get("value")
            row[field] = value
            if payload.get("type"):
                row[f"{field}__type"] = payload.get("type")
            if payload.get("xml:lang"):
                row[f"{field}__lang"] = payload.get("xml:lang")
            if payload.get("datatype"):
                row[f"{field}__datatype"] = payload.get("datatype")
        rows.append(row)
    return rows


def execute_sparql(
    endpoint: str,
    query: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
    user_agent: str,
) -> dict[str, Any]:
    payload = urllib.parse.urlencode({"query": query, "format": "json"}).encode("utf-8")
    headers = {
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": user_agent,
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(delay * attempt)
    assert last_error is not None
    raise RuntimeError(f"Не удалось выполнить запрос после {retries} попыток: {last_error}")


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_filters(values: list[str]) -> set[str]:
    return {value.strip() for value in values if value.strip()}


def select_topics(registry: dict[str, Any], selected_slugs: set[str]) -> list[dict[str, Any]]:
    topics = registry.get("topics", [])
    if not selected_slugs:
        return topics
    matched = [topic for topic in topics if topic["slug"] in selected_slugs]
    missing = sorted(selected_slugs - {topic["slug"] for topic in matched})
    if missing:
        raise ValueError(f"Неизвестные темы: {', '.join(missing)}")
    return matched


def select_queries(topic: dict[str, Any], selected_queries: set[str]) -> list[dict[str, Any]]:
    queries = topic.get("queries", [])
    if not selected_queries:
        return queries
    matched = [query for query in queries if query["name"] in selected_queries]
    missing = sorted(selected_queries - {query["name"] for query in matched})
    if missing:
        raise ValueError(
            f"Для темы {topic['slug']} не найдены запросы: {', '.join(missing)}"
        )
    return matched


def print_topics(registry: dict[str, Any]) -> None:
    for topic in registry.get("topics", []):
        print(f"- {topic['slug']}: {topic['title']}")


def print_queries(registry: dict[str, Any]) -> None:
    for topic in registry.get("topics", []):
        print(f"\n{topic['slug']} — {topic['title']}")
        for query in topic.get("queries", []):
            print(f"  - {query['name']} ({query['const_name']})")


def main() -> int:
    args = parse_args()
    registry = load_registry(args.registry)
    root_dir = Path(__file__).resolve().parent.parent
    endpoint = registry.get("endpoint", "https://query.wikidata.org/sparql")

    if args.list_topics:
        print_topics(registry)
        return 0

    if args.list_queries:
        print_queries(registry)
        return 0

    selected_topics = select_topics(registry, normalize_filters(args.topic))
    selected_query_names = normalize_filters(args.query)

    overall_results: list[QueryResult] = []

    for topic in selected_topics:
        topic_slug = topic["slug"]
        topic_title = topic["title"]
        data_dir = (args.registry.parent / topic["data_dir"]).resolve()
        wikidata_dir = data_dir / "wikidata"
        topic_queries = select_queries(topic, selected_query_names)

        summary_queries: list[dict[str, Any]] = []
        print(f"\n=== {topic_slug} — {topic_title} ===")

        for query_info in topic_queries:
            query_name = query_info["name"]
            const_name = query_info["const_name"]
            raw_path = wikidata_dir / f"{query_name}.raw.json"
            normalized_path = wikidata_dir / f"{query_name}.normalized.json"

            if args.dry_run:
                print(f"[DRY-RUN] {topic_slug}:{query_name} -> {raw_path.relative_to(root_dir)}")
                summary_queries.append({
                    "name": query_name,
                    "const_name": const_name,
                    "status": "planned",
                    "raw_file": str(raw_path.relative_to(data_dir)),
                    "normalized_file": str(normalized_path.relative_to(data_dir)),
                })
                continue

            if raw_path.exists() and normalized_path.exists() and not args.force:
                print(f"[ SKIP ] {topic_slug}:{query_name} — файлы уже есть, используйте --force")
                result = QueryResult(
                    topic_slug=topic_slug,
                    topic_title=topic_title,
                    query_name=query_name,
                    const_name=const_name,
                    status="skipped",
                    raw_file=str(raw_path.relative_to(data_dir)),
                    normalized_file=str(normalized_path.relative_to(data_dir)),
                    skipped_reason="already_exists",
                    started_at=utc_now(),
                    finished_at=utc_now(),
                )
                overall_results.append(result)
                summary_queries.append(result.__dict__)
                continue

            print(f"[ RUN ] {topic_slug}:{query_name}")
            started_at = utc_now()
            try:
                raw_response = execute_sparql(
                    endpoint,
                    query_info["query"],
                    timeout=args.timeout,
                    retries=args.retries,
                    delay=args.delay,
                    user_agent=args.user_agent,
                )
                normalized_rows = flatten_bindings(raw_response)
                save_json(raw_path, raw_response)
                save_json(normalized_path, normalized_rows)
                result = QueryResult(
                    topic_slug=topic_slug,
                    topic_title=topic_title,
                    query_name=query_name,
                    const_name=const_name,
                    status="success" if normalized_rows else "empty",
                    row_count=len(normalized_rows),
                    raw_file=str(raw_path.relative_to(data_dir)),
                    normalized_file=str(normalized_path.relative_to(data_dir)),
                    started_at=started_at,
                    finished_at=utc_now(),
                )
                print(f"[ OK ] {topic_slug}:{query_name} — строк: {len(normalized_rows)}")
            except Exception as exc:
                result = QueryResult(
                    topic_slug=topic_slug,
                    topic_title=topic_title,
                    query_name=query_name,
                    const_name=const_name,
                    status="error",
                    error=str(exc),
                    started_at=started_at,
                    finished_at=utc_now(),
                )
                print(f"[ ERR ] {topic_slug}:{query_name} — {exc}")

            overall_results.append(result)
            summary_queries.append(result.__dict__)
            time.sleep(args.delay)

        if not args.dry_run:
            summary = {
                "topic": topic_title,
                "topic_slug": topic_slug,
                "generated_at": utc_now(),
                "endpoint": endpoint,
                "seed_labels": topic.get("seed_labels", []),
                "queries": summary_queries,
                "totals": {
                    "planned": len(topic_queries),
                    "success": sum(1 for item in summary_queries if item.get("status") == "success"),
                    "empty": sum(1 for item in summary_queries if item.get("status") == "empty"),
                    "skipped": sum(1 for item in summary_queries if item.get("status") == "skipped"),
                    "error": sum(1 for item in summary_queries if item.get("status") == "error"),
                }
            }
            save_json(data_dir / "wikidata_export.json", summary)

    if args.dry_run:
        print("\nDry-run завершён: сеть не использовалась.")
        return 0

    success_count = sum(1 for item in overall_results if item.status == "success")
    empty_count = sum(1 for item in overall_results if item.status == "empty")
    skipped_count = sum(1 for item in overall_results if item.status == "skipped")
    error_count = sum(1 for item in overall_results if item.status == "error")

    print("\n=== Сводка ===")
    print(f"Успешно: {success_count}")
    print(f"Пусто: {empty_count}")
    print(f"Пропущено: {skipped_count}")
    print(f"Ошибок: {error_count}")

    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
