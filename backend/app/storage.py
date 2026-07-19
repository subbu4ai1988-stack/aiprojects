import hashlib
import hmac
import io
import mimetypes
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from .config import DATA_DIR, settings

router = APIRouter(prefix="/api/storage", tags=["storage"])


class ObjectStorage:
    def __init__(self) -> None:
        self.provider = settings.storage_provider
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url or None,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                config=Config(s3={"addressing_style": "path"}),
            )
        return self._client

    @staticmethod
    def _safe_local_path(key: str) -> Path:
        path = (DATA_DIR / key.lstrip("/")).resolve()
        if not path.is_relative_to(DATA_DIR.resolve()):
            raise ValueError("Invalid storage key")
        return path

    @staticmethod
    def _s3_parts(reference: str) -> tuple[str, str]:
        value = reference.removeprefix("s3://")
        bucket, separator, key = value.partition("/")
        if not separator or not bucket or not key:
            raise ValueError("Invalid S3 reference")
        return bucket, key

    def _local_reference_path(self, reference: str) -> Path:
        if reference.startswith("/media/"):
            return self._safe_local_path(f"media/{Path(reference).name}")
        path = Path(reference)
        return path if path.is_absolute() else self._safe_local_path(reference)

    def put_bytes(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        if self.provider == "s3":
            self.client.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            return f"s3://{settings.s3_bucket}/{key}"
        path = self._safe_local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def read_bytes(self, reference: str) -> tuple[bytes, str, str]:
        if reference.startswith("s3://"):
            bucket, key = self._s3_parts(reference)
            response = self.client.get_object(Bucket=bucket, Key=key)
            return (
                response["Body"].read(),
                response.get("ContentType") or "application/octet-stream",
                Path(key).name,
            )
        path = self._local_reference_path(reference)
        if not path.is_file():
            raise FileNotFoundError(reference)
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.name

    def delete(self, reference: str) -> bool:
        try:
            if reference.startswith("s3://"):
                bucket, key = self._s3_parts(reference)
                self.client.delete_object(Bucket=bucket, Key=key)
                return True
            path = self._local_reference_path(reference).resolve()
            if path.is_relative_to(DATA_DIR.resolve()) and path.is_file():
                path.unlink()
                return True
        except (OSError, ValueError):
            return False
        return False

    @contextmanager
    def materialize(self, reference: str):
        if not reference.startswith("s3://"):
            yield self._local_reference_path(reference)
            return
        content, _, filename = self.read_bytes(reference)
        suffix = Path(filename).suffix
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        path = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            yield path
        finally:
            handle.close()
            path.unlink(missing_ok=True)


storage = ObjectStorage()


def signed_download_url(reference: str, lifetime_seconds: int | None = None) -> str:
    expires = int(time.time()) + (lifetime_seconds or settings.storage_signed_url_seconds)
    payload = f"{reference}\n{expires}".encode()
    signature = hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()
    return (
        f"/api/storage/download?reference={quote(reference, safe='')}"
        f"&expires={expires}&signature={signature}"
    )


def verify_download(reference: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    payload = f"{reference}\n{expires}".encode()
    expected = hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.get("/download")
def download_object(
    reference: str = Query(min_length=1),
    expires: int = Query(gt=0),
    signature: str = Query(min_length=32),
):
    if not verify_download(reference, expires, signature):
        raise HTTPException(403, "Download link is invalid or expired")
    try:
        content, content_type, filename = storage.read_bytes(reference)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Stored object not found") from None
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "private, no-store"},
    )
