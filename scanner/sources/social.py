"""Social velocity — the primary signal.

We do NOT care about raw mention counts (those favour mega-caps). We care
about the *rate of change* of attention: mentions accelerating from a low
base, driven by many distinct authors, is the reflexive-loop fingerprint.

Sources, best-effort and independently optional:
  * StockTwits  — public streams endpoint, no key (rate-limited)
  * X / Twitter — API v2 recent search, needs X_BEARER_TOKEN
  * Reddit      — PRAW over WSB-style subs, needs client id/secret

Each source yields message timestamps; we bucket them into "recent" vs
"prior" windows to derive velocity and acceleration.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import requests

import config

log = logging.getLogger("scanner.social")

RECENT_HOURS = 6      # the leading edge
PRIOR_HOURS = 6       # the comparison window immediately before it


@dataclass
class SocialSnapshot:
    symbol: str
    mentions_recent: int
    mentions_prior: int
    unique_authors_recent: int
    sources_live: int          # how many providers actually answered

    @property
    def velocity(self) -> float:
        """Growth rate of mentions, recent vs prior window."""
        base = max(self.mentions_prior, 1)
        return (self.mentions_recent - self.mentions_prior) / base

    @property
    def acceleration(self) -> float:
        """Reflexive tell: recent window running hot on an absolute basis
        while also outpacing the prior window. Scaled by breadth of authors."""
        breadth = min(self.unique_authors_recent / 10.0, 3.0)
        return self.velocity * (1.0 + breadth)


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
        recent, prior, authors, live = 0, 0, set(), 0
        for fetch in (self._stocktwits, self._x, self._reddit_mentions):
            try:
                stamps = fetch(symbol)
            except Exception as exc:  # noqa: BLE001
                log.debug("%s failed for %s: %s", fetch.__name__, symbol, exc)
                stamps = None
            if stamps is None:
                continue
            live += 1
            now = _now()
            for ts, author in stamps:
                age_h = (now - ts).total_seconds() / 3600.0
                if 0 <= age_h < RECENT_HOURS:
                    recent += 1
                    if author:
                        authors.add((fetch.__name__, author))
                elif RECENT_HOURS <= age_h < RECENT_HOURS + PRIOR_HOURS:
                    prior += 1
        return SocialSnapshot(symbol, recent, prior, len(authors), live)

    # --- StockTwits (no key) ----------------------------------------------
    def _stocktwits(self, symbol: str) -> list[tuple[dt.datetime, str]] | None:
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
            user = (m.get("user") or {}).get("username")
            if ts:
                out.append((ts, user))
        return out

    # --- X / Twitter API v2 -----------------------------------------------
    def _x(self, symbol: str) -> list[tuple[dt.datetime, str]] | None:
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
                out.append((ts, t.get("author_id")))
        return out

    # --- Reddit (PRAW) -----------------------------------------------------
    def _reddit_mentions(self, symbol: str) -> list[tuple[dt.datetime, str]] | None:
        if not self._reddit:
            return None
        out = []
        subs = "wallstreetbets+stocks+pennystocks+shortsqueeze"
        for post in self._reddit.subreddit(subs).search(symbol, sort="new", time_filter="day", limit=50):
            ts = dt.datetime.fromtimestamp(post.created_utc, tz=dt.timezone.utc)
            author = str(post.author) if post.author else None
            out.append((ts, author))
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
