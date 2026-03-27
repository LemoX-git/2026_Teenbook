#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SECTION_WORK = ROOT / 'WORK' / 'ya_i_cifrovoy_mir'
SECTION_WEB = ROOT / 'WEB' / 'ya_i_cifrovoy_mir'
SECTION_CONCEPTS = SECTION_WORK / 'concepts.json'

SYNONYM_GROUPS = [
    ['экранное время', 'screen time'],
    ['телефон', 'смартфон', 'smartphone', 'phone', 'mobile phone'],
    ['сон', 'sleep'],
    ['внимание', 'attention', 'focus'],
    ['цифровой детокс', 'digital detox'],
    ['скроллинг', 'лента', 'social media', 'feed', 'timeline'],
    ['игры', 'игра', 'видеоигра', 'video game', 'computer game'],
    ['онлайн-игра', 'online game'],
    ['киберспорт', 'esports', 'e-sport'],
    ['донат', 'донаты', 'microtransaction', 'microtransactions', 'in-app purchase'],
    ['сообщество', 'community', 'virtual community'],
    ['новости', 'news'],
    ['фейк', 'ложная информация', 'misinformation', 'fake news'],
    ['бот', 'bot'],
    ['тролль', 'troll', 'интернет-тролль'],
    ['рекомендации', 'алгоритм рекомендаций', 'recommender system', 'recommendation system'],
    ['приватность', 'privacy'],
    ['персональные данные', 'personal data'],
    ['кибербуллинг', 'cyberbullying', 'интернет-травля'],
    ['цифровой след', 'digital footprint'],
    ['фишинг', 'phishing'],
    ['виртуальная личность', 'online identity', 'digital identity'],
    ['социальная сеть', 'social network', 'social media'],
    ['отношения', 'interpersonal relationship'],
    ['fomo', 'fear of missing out', 'боязнь пропустить интересное'],
    ['устройство', 'device', 'hardware'],
    ['компьютер', 'computer'],
    ['ноутбук', 'laptop'],
    ['аккумулятор', 'battery'],
    ['приложение', 'app', 'application', 'software'],
    ['апгрейд', 'upgrade'],
    ['ремонт', 'repair'],
    ['память', 'memory', 'storage'],
    ['безопасность', 'security', 'safety'],
]

RELATION_BLACKLIST = {
    'описывается в источнике',
    'изучается в',
    'практикуется',
    'сделано из',
    'продукция',
    'different from',
    "topic's main category",
}

ENTITY_BLACKLIST = {
    'оскорбление действием', 'артиллерийская батарея', 'побои',
    'sleep()', 'gnu coreutils', 'dh-59'
}

TOKEN_RE = re.compile(r"[\w\-]+", flags=re.UNICODE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Обновляет WEB-страницы по локальным ответам Wikidata.')
    parser.add_argument('--topic', action='append', default=[], help='Slug подтемы, можно передать несколько раз.')
    parser.add_argument('--article', action='append', default=[], help='Slug статьи, можно передать несколько раз.')
    parser.add_argument('--dry-run', action='store_true', help='Показать, какие файлы будут обновлены.')
    parser.add_argument('--limit-entities', type=int, default=4, help='Сколько сущностей показывать в каждой статье.')
    parser.add_argument('--limit-relations', type=int, default=4, help='Сколько связей показывать в каждой статье.')
    parser.add_argument('--limit-examples', type=int, default=3, help='Сколько обобщённых примеров показывать в каждой статье.')
    return parser.parse_args()


def normalize(text: str | None) -> str:
    text = (text or '').replace('ё', 'е').lower().strip()
    text = re.sub(r'[_/]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def tokenise(text: str | None) -> set[str]:
    return {tok for tok in TOKEN_RE.findall(normalize(text)) if len(tok) > 1}


SYNONYM_MAP: dict[str, set[str]] = {}
for group in SYNONYM_GROUPS:
    group_norm = {normalize(x) for x in group}
    for item in group_norm:
        SYNONYM_MAP[item] = set(group_norm)


def expand_terms(terms: list[str]) -> tuple[set[str], set[str]]:
    phrases: set[str] = set()
    tokens: set[str] = set()
    for term in terms:
        n = normalize(term)
        if not n:
            continue
        phrases.add(n)
        phrases.update(SYNONYM_MAP.get(n, set()))
        tokens.update(tokenise(n))
        for tok in tokenise(n):
            tokens.add(tok)
            tokens.update(tokenise(' '.join(SYNONYM_MAP.get(tok, set()))))
    return phrases, tokens


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def iter_text_values(row: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in row.items():
        if key.endswith('__type') or key.endswith('__lang') or key.endswith('__datatype'):
            continue
        if isinstance(value, str):
            result.append(value)
    return result


def row_labels(row: dict[str, Any]) -> list[str]:
    keys = [
        'itemLabel', 'relatedLabel', 'item1Label', 'item2Label', 'sourceLabel', 'targetLabel',
        'label', 'seedLabel', 'propLabel'
    ]
    labels = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            labels.append(value)
    return labels


def build_article_terms(article: dict[str, Any], topic: dict[str, Any]) -> tuple[set[str], set[str]]:
    inputs: list[str] = []
    inputs.extend([article.get('title', ''), article.get('summary', '')])
    inputs.extend(article.get('keywords', []))
    inputs.extend(article.get('aliases', []))
    inputs.extend(article.get('wikidata_seed_labels', []))
    inputs.extend(topic.get('keywords', []))
    return expand_terms(inputs)


def score_row(row: dict[str, Any], phrases: set[str], tokens: set[str]) -> int:
    labels = [normalize(x) for x in row_labels(row)]
    row_tokens = set()
    for label in labels:
        row_tokens.update(tokenise(label))
    score = 0
    for label in labels:
        if not label:
            continue
        if label in ENTITY_BLACKLIST:
            score -= 50
        if label in phrases:
            score += 12
        for phrase in phrases:
            if phrase and len(phrase) >= 4 and (phrase in label or label in phrase):
                score += 5
    overlap = tokens & row_tokens
    score += len(overlap) * 2
    if any('а' <= ch <= 'я' for label in labels for ch in label):
        score += 1
    prop = normalize(row.get('propLabel'))
    if prop in RELATION_BLACKLIST:
        score -= 6
    if row.get('itemLabel') and normalize(str(row.get('itemLabel'))) in ENTITY_BLACKLIST:
        score -= 20
    return score


def dedupe_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        url = row.get('item') or row.get('related') or row.get('entity')
        label = row.get('itemLabel') or row.get('relatedLabel') or row.get('label')
        if not label or not url:
            continue
        key = normalize(label)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def wikidata_link(url: str | None) -> str:
    if not url:
        return ''
    return url.replace('http://', 'https://')


def rank_entities(data_dir: Path, phrases: set[str], tokens: set[str]) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for name in ['find_by_label.normalized.json', 'expand_class_tree.normalized.json']:
        path = data_dir / name
        if not path.exists():
            continue
        rows = load_json(path)
        for row in rows:
            score = score_row(row, phrases, tokens)
            label = normalize(row.get('itemLabel') or row.get('relatedLabel') or row.get('label'))
            if score <= 0 or label in ENTITY_BLACKLIST:
                continue
            candidates.append((score, row))
    ordered = [row for _, row in sorted(candidates, key=lambda x: (-x[0], normalize(x[1].get('itemLabel') or x[1].get('relatedLabel') or '')))]
    return dedupe_entities(ordered)


def rank_relations(data_dir: Path, phrases: set[str], tokens: set[str]) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for name in ['local_graph.normalized.json']:
        path = data_dir / name
        if not path.exists():
            continue
        rows = load_json(path)
        for row in rows:
            prop = normalize(row.get('propLabel'))
            if prop in RELATION_BLACKLIST:
                continue
            score = score_row(row, phrases, tokens)
            if score <= 1:
                continue
            candidates.append((score, row))
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for score, row in sorted(candidates, key=lambda x: (-x[0], normalize(x[1].get('propLabel') or ''))):
        left = row.get('item1Label') or row.get('sourceLabel') or row.get('itemLabel') or ''
        right = row.get('item2Label') or row.get('targetLabel') or row.get('relatedLabel') or ''
        prop = row.get('propLabel') or row.get('relation') or ''
        key = (normalize(left), normalize(prop), normalize(right))
        if key in seen or not left or not right or not prop:
            continue
        seen.add(key)
        result.append(row)
    return result


def reverse_examples(data_dir: Path, phrases: set[str], tokens: set[str]) -> list[str]:
    path = data_dir / 'reverse_graph.normalized.json'
    if not path.exists():
        return []
    rows = load_json(path)
    counter: Counter[str] = Counter()
    for row in rows:
        score = score_row(row, phrases, tokens)
        if score <= 1:
            continue
        target = row.get('item2Label') or row.get('targetLabel') or ''
        prop = row.get('propLabel') or row.get('relation') or ''
        if not target or normalize(prop) in RELATION_BLACKLIST:
            continue
        counter[f"{target}|{prop}"] += 1
    examples = []
    for key, count in counter.most_common(6):
        target, prop = key.split('|', 1)
        examples.append(f"В обратных связях понятие **{target}** встречается как узел с отношением **{prop}** не меньше {count} раз.")
    return examples


def article_lookup() -> dict[str, dict[str, Any]]:
    data = load_json(SECTION_CONCEPTS)
    return {article['slug']: article for article in data['articles']}


def relative_link(from_md: Path, to_md: Path) -> str:
    return os.path.relpath(to_md, start=from_md.parent).replace('\\', '/')


def render_article(article: dict[str, Any], topic_data: dict[str, Any], article_map: dict[str, dict[str, Any]], entities: list[dict[str, Any]], relations: list[dict[str, Any]], examples: list[str], entity_limit: int, relation_limit: int, example_limit: int) -> str:
    md_path = ROOT / article['web_path']
    section_index = SECTION_WEB / 'index.md'
    topic_index = SECTION_WEB / topic_data['topic']['slug'] / 'index.md'
    nav_to_topic = relative_link(md_path, topic_index)
    nav_to_section = relative_link(md_path, section_index)

    lines: list[str] = []
    lines.append(f"# {article['title']}")
    lines.append('')
    lines.append('> Страница обновлена автоматически по локальным ответам Wikidata. Это черновик, который удобно потом доработать вручную.')
    lines.append('')
    lines.append('## О чём эта статья')
    lines.append('')
    lines.append(article['summary'])
    lines.append('')

    lines.append('## Что нашлось в Wikidata')
    lines.append('')
    if entities:
        for row in entities[:entity_limit]:
            label = row.get('itemLabel') or row.get('relatedLabel') or row.get('label') or 'Понятие'
            uri = wikidata_link(row.get('item') or row.get('related') or row.get('entity'))
            seed = row.get('label') or row.get('seedLabel')
            details = []
            if seed and normalize(seed) != normalize(label):
                details.append(f"найдено по запросу для **{seed}**")
            if row.get('relation'):
                details.append(f"через связь **{row['relation']}**")
            tail = f" — {', '.join(details)}" if details else ''
            lines.append(f"- **{label}**{tail}. [Wikidata]({uri})")
    else:
        lines.append('- Для этой статьи пока не нашлось достаточно точных сущностей; можно повторить выгрузку после уточнения seed-терминов.')
    lines.append('')

    lines.append('## Связи, которые видны в данных')
    lines.append('')
    if relations:
        for row in relations[:relation_limit]:
            left = row.get('item1Label') or row.get('sourceLabel') or row.get('itemLabel') or 'Источник'
            prop = row.get('propLabel') or row.get('relation') or 'связано с'
            right = row.get('item2Label') or row.get('targetLabel') or row.get('relatedLabel') or 'цель'
            lines.append(f"- **{left}** → **{prop}** → **{right}**")
    else:
        lines.append('- Для этой статьи пока не найдено достаточно осмысленных связей в локальной выгрузке.')
    lines.append('')

    lines.append('## Что это даёт для текста')
    lines.append('')
    keyword_text = ', '.join(article.get('keywords', []))
    lines.append(
        f"По этим данным можно опереться на реальные сущности и связи вокруг темы **{article['title']}**. "
        f"В черновике статьи полезно объяснить, как понятия **{keyword_text}** связаны друг с другом и почему это важно в повседневной цифровой жизни."
    )
    lines.append('')

    lines.append('## Что ещё посмотреть в данных')
    lines.append('')
    if examples:
        for example in examples[:example_limit]:
            lines.append(f"- {example}")
    else:
        lines.append('- Обратных примеров пока мало; можно расширить SPARQL-запросы по этой подтеме.')
    lines.append('')

    lines.append('## Связанные статьи')
    lines.append('')
    for slug in article.get('related_articles', []):
        related = article_map.get(slug)
        if not related:
            continue
        rel_link = relative_link(md_path, ROOT / related['web_path'])
        lines.append(f"- [{related['title']}]({rel_link})")
    if not article.get('related_articles'):
        lines.append('- Связанные статьи пока не указаны.')
    lines.append('')

    lines.append('## Теги')
    lines.append('')
    lines.append(', '.join(article.get('keywords', [])))
    lines.append('')

    lines.append('## Источники данных')
    lines.append('')
    lines.append(f"- `WORK/ya_i_cifrovoy_mir/{topic_data['topic']['slug']}/data/wikidata/find_by_label.normalized.json`")
    lines.append(f"- `WORK/ya_i_cifrovoy_mir/{topic_data['topic']['slug']}/data/wikidata/local_graph.normalized.json`")
    lines.append(f"- `WORK/ya_i_cifrovoy_mir/{topic_data['topic']['slug']}/data/wikidata/reverse_graph.normalized.json`")
    lines.append('')

    lines.append('## Навигация по разделу')
    lines.append('')
    lines.append(f"- [К подтеме «{topic_data['topic']['title']}»]({nav_to_topic})")
    lines.append(f"- [К главной странице раздела]({nav_to_section})")
    lines.append('')
    return '\n'.join(lines)


def selected(items: list[dict[str, Any]], arg_values: list[str], key: str) -> list[dict[str, Any]]:
    if not arg_values:
        return items
    wanted = set(arg_values)
    return [item for item in items if item.get(key) in wanted]


def main() -> None:
    args = parse_args()
    section = load_json(SECTION_CONCEPTS)
    article_map = article_lookup()
    topics = selected(section['topics'], args.topic, 'slug')
    updated = 0

    for topic in topics:
        topic_work = SECTION_WORK / topic['slug']
        topic_concepts_path = topic_work / 'concepts.json'
        if not topic_concepts_path.exists():
            print(f'[skip] Нет файла {topic_concepts_path}')
            continue
        topic_data = load_json(topic_concepts_path)
        data_dir = topic_work / 'data' / 'wikidata'
        articles = selected(topic_data['articles'], args.article, 'slug')
        for article in articles:
            phrases, tokens = build_article_terms(article, topic_data['topic'])
            entities = rank_entities(data_dir, phrases, tokens)
            relations = rank_relations(data_dir, phrases, tokens)
            examples = reverse_examples(data_dir, phrases, tokens)
            content = render_article(article, topic_data, article_map, entities, relations, examples, args.limit_entities, args.limit_relations, args.limit_examples)
            out_path = ROOT / article['web_path']
            if args.dry_run:
                print(f'[dry-run] {out_path}')
            else:
                out_path.write_text(content + '\n', encoding='utf-8')
                print(f'[updated] {out_path.relative_to(ROOT)}')
                updated += 1
    if not args.dry_run:
        print(f'Готово: обновлено {updated} markdown-страниц.')


if __name__ == '__main__':
    main()
