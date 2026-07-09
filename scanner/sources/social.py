"""Social velocity — the primary signal, now sentiment-aware.

We do NOT care about raw mention counts (those favour mega-caps) and we do NOT
treat all attention equally: the reflexive UP-loop is driven by *bullish*
attention accelerating. "shorting this / puts / rug" is the opposite signal and
must not inflate the score. So every message carries a sentiment (+1/-1/0) and
we bucket bull vs bear across recent/prior windows.

Sources, best-effort and independently optional:
  * StockTwits  — public streams, no key; uses its native Bullish/Bearish tag
  * X / Twitter — API v2 recent search, needs X_BEARER_TOKEN
  * Reddit      — PRAW over WSB-style subs, needs client id/secret

Each source yields (timestamp, author, sentiment) tuples.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import requests

import config
from scanner.sentiment import classify

log = logging.getLogger("scanner.social")

RECENT_HOURS = 6      # the leading edge
PRIOR_HOURS = 6       # the comparison window immediately before it


@dataclass
class SocialSnapshot:
    symbol: str
    bull_recent: int
    bear_recent: int
    bull_prior: int
    bear_prior: int
    unique_authors_recent: int
    sources_live: int          # how many providers actually answered

    @property
    def mentions_recent(self) -> int:
        return self.bull_recent + self.bear_recent

    @property
    def net_recent(self) -> int:
        return self.bull_recent - self.bear_recent

    @property
    def bull_ratio(self) -> float:
        """Share of directional mentions that are bullish (0..1). 0.5 if none."""
        directional = self.bull_recent + self.bear_recent
        return self.bull_recent / directional if directional else 0.5

    @property
    def bull_velocity(self) -> float:
        """Growth rate of BULLISH mentions, recent vs prior window."""
        base = max(self.bull_prior, 1)
        return (self.bull_recent - self.bull_prior) / base

    @property
    def acceleration(self) -> float:
        """Reflexive tell: bullish attention accelerating, weighted by author
        breadth (not one spammer) and damped when attention is net-bearish."""
        breadth = min(self.unique_authors_recent / 10.0, 3.0)
        direction = 0.3 + 0.7 * self.bull_ratio  # 0.3 (all bear) .. 1.0 (all bull)
        return max(self.bull_velocity, 0.0) * (1.0 + breadth) * direction

    # Backwards-compatible alias used in older reports.
    @property
    def velocity(self) -> float:
        return self.bull_velocity


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Social:
    def __init__(self) -> None:
        self.x_token = config.X_BEARER_TOKEN
        self._reddit = self._init_reddit()

    def _init_reddit(self):
        if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
            return None
        try:
            import praw
            return praw.Reddit(
                client_id=config.REDDIT_CLIENT_ID,
                client_secret=config.REDDIT_CLIENT_SECRET,
                user_agent=config.REDDIT_USER_AGENT,
                check_for_async=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("reddit init failed: %s", exc)
            return None

    def snapshot(self, symbol: str) -> SocialSnapshot:
        bull_r = bear_r = bull_p = bear_p = 0
        authors: set = set()
        live = 0
        for fetch in (self._stocktwits, self._x, self._reddit_mentions):
            try:
                items = fetch(symbol)
            except Exception as exc:  # noqa: BLE001
                log.debug("%s failed for %s: %s", fetch.__name__, symbol, exc)
                items = None
            if items is None:
                continue
            live += 1
            now = _now()
            for ts, author, sent in items:
                age_h = (now - ts).total_seconds() / 3600.0
                if 0 <= age_h < RECENT_HOURS:
                    if sent >= 0:
                        bull_r += 1
                    else:
                        bear_r += 1
                    if author:
                        authors.add((fetch.__name__, author))
                elif RECENT_HOURS <= age_h < RECENT_HOURS + PRIOR_HOURS:
                    if sent >= 0:
                        bull_p += 1
                    else:
                        bear_p += 1
        return SocialSnapshot(symbol, bull_r, bear_r, bull_p, bear_p, len(authors), live)

    # --- StockTwits (no key; native sentiment) ----------------------------
    def _stocktwits(self, symbol: str) -> list[tuple[dt.datetime, str, int]] | None:
        r = requests.get(
            f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json",
            timeout=15,
            headers={"User-Agent": config.REDDIT_USER_AGENT},
        )
        if r.status_code != 200:
            return None
        out = []
        for m in r.json().get("messages", []):
            ts = _parse(m.get("created_at"))
            if not ts:
                continue
            user = (m.get("user") or {}).get("username")
            basic = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            if basic == "Bullish":
                sent = 1
            elif basic == "Bearish":
                sent = -1
            else:
                sent = classify(m.get("body"))  # untagged -> lexicon
            out.append((ts, user, sent))
        return out

    # --- X / Twitter API v2 -----------------------------------------------
    def _x(self, symbol: str) -> list[tuple[dt.datetime, str, int]] | None:
        if not self.x_token:
            return None
        r = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {self.x_token}"},
            params={
                "query": f"(${symbol}) -is:retweet lang:en",
                "max_results": 100,
                "tweet.fields": "created_at,author_id",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        out = []
        for t in r.json().get("data", []):
            ts = _parse(t.get("created_at"))
            if ts:
                out.append((ts, t.get("author_id"), classify(t.get("text"))))
        return out

    # --- Reddit (PRAW) -----------------------------------------------------
    def _reddit_mentions(self, symbol: str) -> list[tuple[dt.datetime, str, int]] | None:
        if not self._reddit:
            return None
        out = []
        subs = "wallstreetbets+stocks+pennystocks+shortsqueeze"
        for post in self._reddit.subreddit(subs).search(symbol, sort="new", time_filter="day", limit=50):
            ts = dt.datetime.fromtimestamp(post.created_utc, tz=dt.timezone.utc)
            author = str(post.author) if post.author else None
            text = f"{post.title} {getattr(post, 'selftext', '')}"
            out.append((ts, author, classify(text)))
        return out


def _parse(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:  # ISO 8601 with offset
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
