from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from enum import StrEnum

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from infrai_storage import InfraiError, InfraiStorage
from release_thumbnail import InvalidImage, render_thumbnail


class BuildState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReleaseAction(StrEnum):
    PREVIEW = "preview"
    PUBLISH = "publish"


class BuildEvent(BaseModel):
    build_id: str = Field(min_length=1, max_length=80)
    state: BuildState
    commit_sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")


class ReleaseOperation(BaseModel):
    release_id: str = Field(min_length=1, max_length=80)
    action: ReleaseAction


class ImageUploadRequest(BaseModel):
    image_base64: str
    source_name: str = Field(min_length=1, max_length=120)
    build: BuildEvent
    release: ReleaseOperation
    max_width: int = Field(default=1200, ge=64, le=2400)
    max_height: int = Field(default=630, ge=64, le=2400)


class UploadDiagnostics(BaseModel):
    decision: str
    input_name: str
    output_width: int
    output_height: int
    content_type: str


class ImageUploadResult(BaseModel):
    object_key: str
    build_id: str
    release_id: str
    release_action: ReleaseAction
    stored: bool
    diagnostics: UploadDiagnostics


def object_key_for(payload: ImageUploadRequest) -> str:
    identity = f"{payload.release.release_id}:{payload.build.commit_sha}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"release-images/{payload.release.release_id}/{digest}.webp"


def create_app(storage: InfraiStorage | None = None) -> FastAPI:
    bucket = os.environ.get("INFRAI_IMAGE_BUCKET", "developer-tools-images")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        api_key = os.environ.get("INFRAI_API_KEY")
        if storage is None and not api_key:
            raise RuntimeError("INFRAI_API_KEY is required")
        active = storage or InfraiStorage(api_key=api_key or "")
        await active.create_bucket(bucket)
        app.state.storage = active
        yield
        if storage is None:
            await active.close()

    app = FastAPI(title="Developer tools image service", lifespan=lifespan)

    @app.exception_handler(InfraiError)
    async def infrai_error_handler(_request: Request, exc: InfraiError):
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return JSONResponse(status_code=status, content={"detail": exc.detail})

    @app.post("/release-images", response_model=ImageUploadResult)
    async def upload_release_image(payload: ImageUploadRequest, request: Request):
        if payload.build.state is not BuildState.SUCCEEDED:
            raise HTTPException(
                status_code=409,
                detail="release images require a succeeded build",
            )
        try:
            thumbnail = render_thumbnail(
                payload.image_base64, payload.max_width, payload.max_height
            )
        except InvalidImage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        key = object_key_for(payload)
        idempotency_key = f"release-image:{payload.release.release_id}:{payload.build.commit_sha}"
        upload_url = await request.app.state.storage.presign_put(
            bucket,
            key,
            content_type=thumbnail.content_type,
            max_bytes=len(thumbnail.content),
            idempotency_key=idempotency_key,
        )
        await request.app.state.storage.put_signed(
            upload_url, thumbnail.content, thumbnail.content_type
        )
        return ImageUploadResult(
            object_key=key,
            build_id=payload.build.build_id,
            release_id=payload.release.release_id,
            release_action=payload.release.action,
            stored=True,
            diagnostics=UploadDiagnostics(
                decision="resized" if thumbnail.resized else "kept_original_dimensions",
                input_name=payload.source_name,
                output_width=thumbnail.width,
                output_height=thumbnail.height,
                content_type=thumbnail.content_type,
            ),
        )

    return app


app = create_app()


def run() -> None:
    uvicorn.run("devtools_image_service:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
