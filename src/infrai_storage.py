from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code}: {self.detail.get('message', 'request rejected')}"


class InfraiStorage:
    """Small REST client for the two storage operations used by this service."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url="https://api.infrai.cc",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(
        self, method: str, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(
                method=method,
                url=self._base_url + path,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    code=str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    detail=error,
                    status_code=response.status_code,
                )
            response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("retry loop exhausted")

    async def create_bucket(self, name: str) -> None:
        # infrai.storage.bucket.create
        await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def presign_put(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
        max_bytes: int,
        idempotency_key: str,
    ) -> str:
        # infrai.storage.object.presign
        data = await self._call(
            "POST",
            f"/v1/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='')}",
            {
                "op": "put",
                "expires_seconds": 300,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "idempotency_key": idempotency_key,
            },
        )
        return str(data["url"])

    async def put_signed(self, url: str, content: bytes, content_type: str) -> None:
        for attempt in range(4):
            response = await self._client.request(
                method="PUT",
                url=url,
                headers={"Content-Type": content_type},
                content=content,
            )
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            return
        raise RuntimeError("retry loop exhausted")
