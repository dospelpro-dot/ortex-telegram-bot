# ortex-telegram-bot

Telegram-бот, который сканирует US-equities на **ранние рефлексивные петли
розничного внимания** — до того, как их подхватят momentum-кванты и ETF-потоки.
Выдаёт **3 имени** с потенциалом **+15% за 1–3 дня**, приоритет — **social velocity**.

> Миссия и правила проекта зафиксированы в [`CLAUDE.md`](./CLAUDE.md) — Claude Code
> читает их автоматически в каждой сессии.

## Как это работает

```
Кандидаты (StockTwits trending + watchlist)
   → сигналы: market (цена/объём/RSI) · ORTEX (short/CTB) · social (velocity)
   → жёсткие фильтры (ликвидность, не-переразгон, не-мегакап)
   → скоринг: 0.40 social + 0.30 squeeze + 0.20 early + 0.10 retail
   → топ-3 → отчёт в Telegram
```

Каждый источник данных **опционален**: нет ключа — источник мягко отключается,
пайплайн продолжает работать (StockTwits и yfinance работают без ключей).

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env        # впиши TELEGRAM_BOT_TOKEN (от @BotFather) и, по желанию, остальные ключи

python -m scanner.pipeline  # сухой прогон в терминал (без Telegram)
python bot.py               # запустить бота: /scan /status /start
```

## Ключи API (`.env`)

| Переменная            | Зачем                              | Обязательна |
|-----------------------|------------------------------------|-------------|
| `TELEGRAM_BOT_TOKEN`  | запуск бота                        | да          |
| `ORTEX_API_KEY`       | short interest / CTB (squeeze fuel)| нет         |
| `POLYGON_API_KEY`     | рыночные данные (иначе yfinance)   | нет         |
| `X_BEARER_TOKEN`      | social velocity из X               | нет         |
| `REDDIT_CLIENT_ID/SECRET` | social velocity из Reddit      | нет         |

StockTwits (тренды + упоминания) и yfinance работают **без ключей**.

## Бэктест и калибровка

Сканер учится на собственных пиках: каждый скан логирует топ-3 (цена входа +
суб-скоры), а через 1–3 дня меряется фактический max +%.

```bash
python -m scanner.pipeline --log   # скан + лог пиков (/scan в боте логирует сам)
python -m backtest.evaluate        # оценить созревшие пики (после горизонта)
python -m backtest.analyze         # hit-rate, корреляции, предлагаемые веса
```

`analyze` считает корреляцию каждого сигнала (social/squeeze/early/retail) с
реальным движением и предлагает веса ∝ корреляции. При выборке <30 — только
собирает данные (защита от оверфита). В боте всё это — команда `/backtest`.
Лог пиков (`data/picks.jsonl`) хранится локально и не коммитится.

## Тюнинг

Все веса, пороги и горизонт — в `config.py` или через `.env`
(`W_SOCIAL`, `FILTER_MIN_PRICE`, `MISSION_TARGET_MOVE_PCT`, …).

## ⚠️ Дисклеймер

Это исследовательский инструмент, **не инвестиционный совет**. Сигнал носит
вероятностный характер; короткий горизонт означает высокий риск. Решения и
управление риском — на вас.
