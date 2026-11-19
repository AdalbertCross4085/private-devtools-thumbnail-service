import base64
import io

from PIL import Image

from devtools_image_service import (
    BuildEvent,
    BuildState,
    ImageUploadRequest,
    ReleaseAction,
    ReleaseOperation,
    object_key_for,
)
from release_thumbnail import render_thumbnail


def encoded_png(width: int, height: int) -> str:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#2563eb").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def test_wide_build_image_is_resized_without_changing_aspect_ratio() -> None:
    thumbnail = render_thumbnail(encoded_png(2400, 1200), 1200, 630)

    assert (thumbnail.width, thumbnail.height) == (1200, 600)
    assert thumbnail.resized is True
    assert thumbnail.content_type == "image/webp"


def test_object_key_is_stable_for_a_release_and_commit() -> None:
    request = ImageUploadRequest(
        image_base64=encoded_png(10, 10),
        source_name="build-summary.png",
        build=BuildEvent(build_id="build-42", state=BuildState.SUCCEEDED, commit_sha="a1b2c3d"),
        release=ReleaseOperation(release_id="release-9", action=ReleaseAction.PUBLISH),
    )

    assert object_key_for(request) == object_key_for(request)
    assert object_key_for(request).startswith("release-images/release-9/")
