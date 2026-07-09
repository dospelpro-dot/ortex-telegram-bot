"""Data-source adapters. Each returns plain dicts and degrades gracefully
(returns None / empty on missing keys or network errors) so the pipeline
never crashes on a single dead source."""
