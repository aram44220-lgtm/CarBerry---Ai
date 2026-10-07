# Site Engine

Готовая мини-дизайн-система для Telegram-бота, который генерирует красивые сайты.

Идея: LLM не пишет HTML с нуля. Она возвращает JSON-план, а Python собирает сайт из заранее сверстанных компонентов.

## Структура

- `generator.py` — сборка полного сайта
- `components.py` — HTML-компоненты
- `themes.py` — темы/дизайн-токены
- `schema.py` — проверка JSON-плана
- `example_plan.json` — пример плана, который может вернуть AI
- `demo.py` — локальный пример генерации
- `static/site.css` — глобальная система стилей
- `static/site.js` — небольшие интерактивы

## Быстрый запуск

```bash
cd site_engine
python demo.py
```

Откроется файл `demo/index.html`.

## Что должен возвращать AI

```json
{
  "site_type": "restaurant",
  "theme": "noir_gold",
  "font_pair": "editorial",
  "sections": [
    {"type": "navbar", "variant": "glass"},
    {"type": "hero", "variant": "split_editorial"},
    {"type": "stats", "variant": "minimal"},
    {"type": "features", "variant": "bento"},
    {"type": "gallery", "variant": "masonry"},
    {"type": "testimonials", "variant": "editorial"},
    {"type": "cta", "variant": "luxury"},
    {"type": "footer", "variant": "minimal"}
  ],
  "content": {
    "brand": "Luma",
    "title": "A place worth staying for.",
    "subtitle": "A modern dining experience built around fire, seasonal ingredients and slow evenings.",
    "primary_cta": "Reserve a table",
    "secondary_cta": "Explore menu"
  }
}
```

## Важно

Для production можно подключить изображения из Pexels/Unsplash API, а AI оставить только планировщиком: выбор темы, блоков, текстов и image queries.
