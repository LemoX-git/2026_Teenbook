from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[3]
SECTION_WORK = ROOT / 'WORK' / 'ya_i_cifrovoy_mir'
SECTION_WEB = ROOT / 'WEB' / 'ya_i_cifrovoy_mir'
SECTION_CONCEPTS = SECTION_WORK / 'concepts.json'

TOKEN_RE = re.compile(r"[\w\-]+", flags=re.UNICODE)
CODE_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*|\s*```$", flags=re.IGNORECASE | re.DOTALL)

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
    'в этом списке перечисляются',
    'платформа',
}

ENTITY_BLACKLIST = {
    'оскорбление действием', 'артиллерийская батарея', 'побои',
    'sleep()', 'gnu coreutils', 'dh-59',
}

SYNONYM_MAP: dict[str, set[str]] = {}
for group in SYNONYM_GROUPS:
    group_norm = {re.sub(r'\s+', ' ', x.replace('ё', 'е').lower().strip()) for x in group}
    for item in group_norm:
        SYNONYM_MAP[item] = set(group_norm)


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    path: str
    model: str
    timeout: int
    temperature: float
    max_tokens: int
    extra_headers: dict[str, str]
    app_name: str
    retries: int
    retry_sleep: float

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.path.lstrip('/')}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Генерирует финальные markdown-страницы через реальный LLM API, используя контекст из Wikidata.'
    )
    parser.add_argument('--topic', action='append', default=[], help='Slug подтемы, можно передать несколько раз.')
    parser.add_argument('--article', action='append', default=[], help='Slug статьи, можно передать несколько раз.')
    parser.add_argument('--dry-run', action='store_true', help='Не вызывать API, только показать, что будет сгенерировано.')
    parser.add_argument('--overwrite', action='store_true', help='Перезаписать даже уже существующие markdown-файлы.')
    parser.add_argument('--limit-entities', type=int, default=6, help='Сколько сущностей Wikidata давать модели на статью.')
    parser.add_argument('--limit-relations', type=int, default=6, help='Сколько связей Wikidata давать модели на статью.')
    parser.add_argument('--max-articles', type=int, default=0, help='Ограничить число статей за один запуск.')
    parser.add_argument('--save-debug', action='store_true', help='Сохранять промпты и сырые ответы модели в WORK/.../data/llm_generation.')
    parser.add_argument('--apply-crosslinks', action='store_true', help='После генерации запустить скрипт перекрёстных ссылок для WEB.')
    parser.add_argument('--temperature', type=float, default=None, help='Переопределить температуру из env.')
    parser.add_argument('--max-tokens', type=int, default=None, help='Переопределить максимум токенов из env.')
    return parser.parse_args()


def normalize(text: str | None) -> str:
    text = (text or '').replace('ё', 'е').lower().strip()
    text = re.sub(r'[_/]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def tokenise(text: str | None) -> set[str]:
    return {tok for tok in TOKEN_RE.findall(normalize(text)) if len(tok) > 1}


def expand_terms(terms: list[str]) -> tuple[set[str], set[str]]:
    phrases: set[str] = set()
    tokens: set[str] = set()
    for term in terms:
        n = normalize(term)
        if not n:
            continue
        phrases.add(n)
        phrases.update(SYNONYM_MAP.get(n, set()))
        tks = tokenise(n)
        tokens.update(tks)
        for tok in tks:
            if tok in SYNONYM_MAP:
                tokens.update(tokenise(' '.join(SYNONYM_MAP[tok])))
    return phrases, tokens


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def article_lookup() -> dict[str, dict[str, Any]]:
    data = load_json(SECTION_CONCEPTS)
    return {article['slug']: article for article in data['articles']}


def selected(items: list[dict[str, Any]], arg_values: list[str], key: str) -> list[dict[str, Any]]:
    if not arg_values:
        return items
    wanted = set(arg_values)
    return [item for item in items if item.get(key) in wanted]


def build_article_terms(article: dict[str, Any], topic: dict[str, Any]) -> tuple[set[str], set[str]]:
    inputs: list[str] = []
    inputs.extend([article.get('title', ''), article.get('summary', '')])
    inputs.extend(article.get('keywords', []))
    inputs.extend(article.get('aliases', []))
    inputs.extend(article.get('wikidata_seed_labels', []))
    inputs.extend(topic.get('keywords', []))
    return expand_terms(inputs)


def row_labels(row: dict[str, Any]) -> list[str]:
    keys = [
        'itemLabel', 'relatedLabel', 'item1Label', 'item2Label', 'sourceLabel', 'targetLabel',
        'label', 'seedLabel', 'propLabel'
    ]
    labels: list[str] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            labels.append(value)
    return labels


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
                score += 4
    score += len(tokens & row_tokens) * 2
    if any('а' <= ch <= 'я' for label in labels for ch in label):
        score += 2
    prop = normalize(row.get('propLabel'))
    if prop in RELATION_BLACKLIST:
        score -= 8
    return score


def dedupe_entities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        label = row.get('itemLabel') or row.get('relatedLabel') or row.get('label')
        if not label:
            continue
        key = normalize(str(label))
        if key in seen or key in ENTITY_BLACKLIST:
            continue
        seen.add(key)
        result.append(row)
    return result


def rank_entities(data_dir: Path, phrases: set[str], tokens: set[str]) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for name in ['find_by_label.normalized.json', 'expand_class_tree.normalized.json']:
        path = data_dir / name
        if not path.exists():
            continue
        rows = load_json(path)
        for row in rows:
            score = score_row(row, phrases, tokens)
            if score <= 0:
                continue
            candidates.append((score, row))
    ordered = [row for _, row in sorted(candidates, key=lambda x: (-x[0], normalize(x[1].get('itemLabel') or x[1].get('relatedLabel') or '')))]
    return dedupe_entities(ordered)


def rank_relations(data_dir: Path, phrases: set[str], tokens: set[str]) -> list[dict[str, Any]]:
    path = data_dir / 'local_graph.normalized.json'
    if not path.exists():
        return []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for row in load_json(path):
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
        if not left or not right or not prop:
            continue
        key = (normalize(left), normalize(prop), normalize(right))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def wikidata_link(url: str | None) -> str:
    if not url:
        return ''
    return str(url).replace('http://', 'https://')


def relative_link(from_md: Path, to_md: Path) -> str:
    return os.path.relpath(to_md, start=from_md.parent).replace('\\', '/')


def load_llm_config(args: argparse.Namespace) -> LLMConfig:
    api_key = os.getenv('LLM_API_KEY', '').strip()
    if not api_key and not args.dry_run:
        raise SystemExit('Не задан LLM_API_KEY. Установите переменные окружения перед запуском.')
    base_url = os.getenv('LLM_API_BASE_URL', 'https://api.openai.com/v1').strip()
    path = os.getenv('LLM_API_PATH', '/chat/completions').strip()
    model = os.getenv('LLM_MODEL', '').strip() or 'gpt-4.1-mini'
    timeout = int(os.getenv('LLM_TIMEOUT', '120'))
    retries = int(os.getenv('LLM_RETRIES', '2'))
    retry_sleep = float(os.getenv('LLM_RETRY_SLEEP', '4'))
    temperature = args.temperature if args.temperature is not None else float(os.getenv('LLM_TEMPERATURE', '0.4'))
    max_tokens = args.max_tokens if args.max_tokens is not None else int(os.getenv('LLM_MAX_TOKENS', '1400'))
    app_name = os.getenv('LLM_APP_NAME', 'teenbook-wikidata-generator')
    extra_headers_raw = os.getenv('LLM_EXTRA_HEADERS_JSON', '').strip()
    extra_headers: dict[str, str] = {}
    if extra_headers_raw:
        try:
            parsed = json.loads(extra_headers_raw)
            if isinstance(parsed, dict):
                extra_headers = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError as exc:
            raise SystemExit(f'LLM_EXTRA_HEADERS_JSON содержит невалидный JSON: {exc}') from exc
    return LLMConfig(
        api_key=api_key,
        base_url=base_url,
        path=path,
        model=model,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_headers=extra_headers,
        app_name=app_name,
        retries=retries,
        retry_sleep=retry_sleep,
    )


def build_context_payload(article: dict[str, Any], topic_data: dict[str, Any], entities: list[dict[str, Any]], relations: list[dict[str, Any]], article_map: dict[str, dict[str, Any]], entity_limit: int, relation_limit: int) -> dict[str, Any]:
    rel_articles = []
    for slug in article.get('related_articles', []):
        related = article_map.get(slug)
        if related:
            rel_articles.append({'slug': related['slug'], 'title': related['title']})

    selected_entities = []
    for row in entities[:entity_limit]:
        label = row.get('itemLabel') or row.get('relatedLabel') or row.get('label') or 'Понятие'
        selected_entities.append({
            'label': label,
            'seed': row.get('label') or row.get('seedLabel') or '',
            'wikidata_url': wikidata_link(row.get('item') or row.get('related') or row.get('entity')),
        })

    selected_relations = []
    for row in relations[:relation_limit]:
        left = row.get('item1Label') or row.get('sourceLabel') or row.get('itemLabel') or 'Источник'
        prop = row.get('propLabel') or row.get('relation') or 'связано с'
        right = row.get('item2Label') or row.get('targetLabel') or row.get('relatedLabel') or 'Цель'
        selected_relations.append({'source': left, 'relation': prop, 'target': right})

    return {
        'section_title': 'Я и цифровой мир',
        'topic_title': topic_data['topic']['title'],
        'topic_slug': topic_data['topic']['slug'],
        'topic_description': topic_data['topic'].get('description', ''),
        'article_slug': article['slug'],
        'article_title': article['title'],
        'article_summary': article['summary'],
        'keywords': article.get('keywords', []),
        'aliases': article.get('aliases', []),
        'wikidata_seed_labels': article.get('wikidata_seed_labels', []),
        'related_articles': rel_articles,
        'wikidata_entities': selected_entities,
        'wikidata_relations': selected_relations,
    }


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    system_prompt = (
        'Ты пишешь статьи для детской онлайн-энциклопедии на русском языке. '
        'Объясняй ясно, дружелюбно и без канцелярита. '
        'Главное правило: объясни для десятилетнего ребенка. '
        'Не используй тяжёлые термины без простого объяснения. '
        'Не выдумывай факты, которых нет в контексте. '
        'Если данных мало, опирайся на общеизвестное объяснение темы, но без ложной конкретики. '
        'Верни только markdown-текст без тройных кавычек и без JSON.'
    )
    user_prompt = f"""
Сгенерируй финальную markdown-статью для детской энциклопедии.

Требования к стилю:
- объясни для десятилетнего ребенка;
- русский язык;
- доброжелательный и понятный тон;
- не менее 5 смысловых абзацев;
- без списков в каждом абзаце, но можно 1-2 небольших списка там, где это действительно помогает;
- не упоминай, что текст написан нейросетью;
- не вставляй технические фразы вроде 'по данным wikidata' в основной текст;
- не используй QID, URI, API, JSON и другие технические слова в основной части статьи;
- не делай разделы 'Что нашлось в Wikidata' или 'Источники данных'.

Структура ответа:
1. В начале строка первого уровня: # {{название статьи}}
2. Затем короткое вводное объяснение.
3. Затем раздел '## Как это понять'.
4. Затем раздел '## Почему это важно'.
5. Затем раздел '## Пример из жизни'.
6. Затем раздел '## Что можно делать на практике'.
7. Затем раздел '## Запомни главное'.

Нельзя:
- придумывать медицинские диагнозы, проценты, исследования и статистику, если их нет в контексте;
- делать пугающий тон;
- писать слишком по-взрослому;
- повторять одни и те же формулировки.

Контекст статьи:
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()
    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]


def call_llm(config: LLMConfig, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    headers = {
        'Authorization': f'Bearer {config.api_key}',
        'Content-Type': 'application/json',
        'User-Agent': config.app_name,
        **config.extra_headers,
    }
    payload = {
        'model': config.model,
        'messages': messages,
        'temperature': config.temperature,
        'max_tokens': config.max_tokens,
    }

    last_error: Exception | None = None
    for attempt in range(config.retries + 1):
        try:
            response = requests.post(config.endpoint, headers=headers, json=payload, timeout=config.timeout)
            response.raise_for_status()
            data = response.json()
            text = extract_text_from_response(data)
            if not text.strip():
                raise ValueError('LLM API вернул пустой текст.')
            return text, {'request': payload, 'response': data}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= config.retries:
                break
            time.sleep(config.retry_sleep)
    raise SystemExit(f'Не удалось получить ответ от LLM API: {last_error}')


def extract_text_from_response(data: dict[str, Any]) -> str:
    if 'choices' in data and data['choices']:
        choice = data['choices'][0]
        message = choice.get('message', {})
        content = message.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get('type') in {'text', 'output_text'} and item.get('text'):
                    parts.append(str(item['text']))
            return '\n'.join(parts)
    if 'output' in data and isinstance(data['output'], list):
        parts: list[str] = []
        for item in data['output']:
            if not isinstance(item, dict):
                continue
            content = item.get('content')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') in {'output_text', 'text'} and block.get('text'):
                        parts.append(str(block['text']))
        return '\n'.join(parts)
    return ''


def clean_markdown(text: str, article_title: str) -> str:
    cleaned = text.strip()
    cleaned = CODE_FENCE_RE.sub('', cleaned).strip()
    if cleaned.startswith('```') and cleaned.endswith('```'):
        cleaned = cleaned[3:-3].strip()
    if not cleaned.startswith('# '):
        cleaned = f'# {article_title}\n\n' + cleaned
    cleaned = cleaned.replace('\r\n', '\n')
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip() + '\n'


def render_footer(article: dict[str, Any], topic_data: dict[str, Any], article_map: dict[str, dict[str, Any]], entities: list[dict[str, Any]]) -> str:
    md_path = ROOT / article['web_path']
    section_index = SECTION_WEB / 'index.md'
    topic_index = SECTION_WEB / topic_data['topic']['slug'] / 'index.md'
    lines: list[str] = []

    lines.append('')
    lines.append('## Связанные статьи')
    lines.append('')
    related_written = 0
    for slug in article.get('related_articles', []):
        related = article_map.get(slug)
        if not related:
            continue
        rel_link = relative_link(md_path, ROOT / related['web_path'])
        lines.append(f"- [{related['title']}]({rel_link})")
        related_written += 1
    if not related_written:
        lines.append('- Связанные статьи пока не указаны.')

    lines.append('')
    lines.append('## Полезные понятия из Wikidata')
    lines.append('')
    if entities:
        for row in entities[:5]:
            label = row.get('itemLabel') or row.get('relatedLabel') or row.get('label') or 'Понятие'
            uri = wikidata_link(row.get('item') or row.get('related') or row.get('entity'))
            lines.append(f'- **{label}** — [Wikidata]({uri})')
    else:
        lines.append('- Для этой статьи пока не найдено достаточно точных сущностей.')

    lines.append('')
    lines.append('## Навигация по разделу')
    lines.append('')
    lines.append(f"- [К подтеме «{topic_data['topic']['title']}»]({relative_link(md_path, topic_index)})")
    lines.append(f"- [К главной странице раздела]({relative_link(md_path, section_index)})")
    lines.append('')
    return '\n'.join(lines)




def apply_crosslinks() -> None:
    script = SECTION_WORK / 'scripts' / 'insert_crosslinks.py'
    subprocess.run([sys.executable, str(script)], check=True)

def topic_llm_dir(topic_slug: str) -> Path:
    return SECTION_WORK / topic_slug / 'data' / 'llm_generation'


def save_debug_artifacts(topic_slug: str, article_slug: str, messages: list[dict[str, str]], raw_payload: dict[str, Any], markdown: str) -> None:
    out_dir = topic_llm_dir(topic_slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f'{article_slug}.messages.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / f'{article_slug}.api_payload.json').write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / f'{article_slug}.generated.md').write_text(markdown, encoding='utf-8')


def main() -> None:
    args = parse_args()
    config = load_llm_config(args)
    section = load_json(SECTION_CONCEPTS)
    article_map = article_lookup()
    topics = selected(section['topics'], args.topic, 'slug')
    generated = 0

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
            if args.max_articles and generated >= args.max_articles:
                print(f'Достигнут лимит max_articles={args.max_articles}.')
                return
            out_path = ROOT / article['web_path']
            if out_path.exists() and not args.overwrite and not args.dry_run:
                print(f'[skip] Уже существует {out_path.relative_to(ROOT)} (добавьте --overwrite для перезаписи)')
                continue
            phrases, tokens = build_article_terms(article, topic_data['topic'])
            entities = rank_entities(data_dir, phrases, tokens)
            relations = rank_relations(data_dir, phrases, tokens)
            context = build_context_payload(article, topic_data, entities, relations, article_map, args.limit_entities, args.limit_relations)
            messages = build_messages(context)

            if args.dry_run:
                print(f"[dry-run] {article['slug']} -> {out_path.relative_to(ROOT)}")
                generated += 1
                continue

            llm_text, raw_payload = call_llm(config, messages)
            cleaned = clean_markdown(llm_text, article['title'])
            footer = render_footer(article, topic_data, article_map, entities)
            final_markdown = cleaned.rstrip() + '\n' + footer
            out_path.write_text(final_markdown, encoding='utf-8')
            print(f'[generated] {out_path.relative_to(ROOT)}')
            if args.save_debug:
                save_debug_artifacts(topic['slug'], article['slug'], messages, raw_payload, final_markdown)
            generated += 1
            time.sleep(1.0)

    if args.dry_run:
        print(f'План генерации готов: {generated} статей.')
    else:
        if args.apply_crosslinks and generated:
            apply_crosslinks()
            print('Дополнительно запущена простановка перекрёстных ссылок.')
        print(f'Готово: сгенерировано {generated} markdown-страниц через LLM API.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('Остановлено пользователем.')
