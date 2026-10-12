"""File storage. `LocalStorage` writes under STORAGE_DIR; the interface allows an S3 backend later."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from anyio import Path as AsyncPath

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def save(self, data: bytes, ext: str = "jpg") -> str: ...
    async def read(self, rel_path: str) -> bytes: ...
    async def delete(self, rel_path: str) -> None: ...
    def url(self, rel_path: str) -> str: ...


class LocalStorage:
    """Saves to `STORAGE_DIR/YYYY/MM/<uuid>.<ext>`; served read-only at `/media`."""

    def __init__(self, root: str, public_base_url: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url.rstrip("/")

    def _abs(self, rel_path: str) -> Path:
        path = (self.root / rel_path).resolve()
        if self.root not in path.parents:
            raise ValueError("path escapes storage root")
        return path

    async def save(self, data: bytes, ext: str = "jpg") -> str:
        now = datetime.now(UTC)
        rel = f"{now:%Y}/{now:%m}/{uuid.uuid4()}.{ext}"
        target = AsyncPath(self._abs(rel))
        await target.parent.mkdir(parents=True, exist_ok=True)
        await target.write_bytes(data)
        return rel

    async def read(self, rel_path: str) -> bytes:
        return await AsyncPath(self._abs(rel_path)).read_bytes()

    async def delete(self, rel_path: str) -> None:
        try:
            await AsyncPath(self._abs(rel_path)).unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.warning("could not delete stored file", extra={"path": rel_path})

    def url(self, rel_path: str) -> str:
        return f"{self.public_base_url}/media/{rel_path}"
