"""Base connector with throttling, cache, and retry logic."""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import httpx
from django.conf import settings
from django.core.cache import cache
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@dataclass
class NormalizedOpportunity:
    """Format interno normalizado — saída de qualquer conector."""

    source: str
    external_id: str
    title: str
    description: str = ""
    modality: str = "other"
    number: str = ""
    process_number: str = ""
    entity_cnpj: str = ""
    entity_name: str = ""
    entity_uf: str = ""
    entity_city: str = ""
    published_at: str | None = None
    proposals_open_at: str | None = None
    proposals_close_at: str | None = None
    deadline: str | None = None
    estimated_value: float | None = None
    awarded_value: float | None = None
    is_srp: bool = False
    link: str = ""
    raw_data: dict = field(default_factory=dict)
    items: list[dict] = field(default_factory=list)
    document_urls: list[dict] = field(default_factory=list)


class BaseConnector(ABC):
    """Base class for government API connectors."""

    def __init__(self, base_url: str, rate_limit_rpm: int = 60):
        self.base_url = base_url.rstrip("/")
        self.rate_limit_rpm = rate_limit_rpm
        self._min_interval = 60.0 / rate_limit_rpm
        self._last_request_time = 0.0
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "LicitaAI/1.0"},
        )

    def _throttle(self):
        """Respect rate limits."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET with throttling, cache, and retry."""
        import hashlib, json
        raw_key = f"connector:{self.__class__.__name__}:{path}:{json.dumps(params, sort_keys=True)}"
        cache_key = hashlib.md5(raw_key.encode()).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        self._throttle()
        logger.info("GET %s%s params=%s", self.base_url, path, params)
        resp = self.client.get(path, params=params)
        resp.raise_for_status()

        if resp.status_code == 204 or not resp.content:
            return {}

        data = resp.json()
        cache.set(cache_key, data, timeout=300)  # 5 min
        return data

    @abstractmethod
    def fetch_opportunities(
        self, date_from: date, date_to: date, **kwargs
    ) -> list[NormalizedOpportunity]:
        """Fetch and normalize opportunities from the source."""
        ...

    @abstractmethod
    def fetch_items(self, opportunity: NormalizedOpportunity) -> list[dict]:
        """Fetch items for a given opportunity."""
        ...

    @abstractmethod
    def fetch_documents(self, opportunity: NormalizedOpportunity) -> list[dict]:
        """Fetch document metadata for a given opportunity."""
        ...

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
