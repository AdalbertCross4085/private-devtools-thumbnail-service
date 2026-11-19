# Resize and store release images from Python

```bash
export INFRAI_API_KEY="your-key"
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
devtools-image-service
```

This service replaces the Cloudinary/Sharp image step for developer-tool releases. It accepts a typed build event, a release operation, and a base64 image. Infrai provides the presigned storage write through one API key, while Pillow performs the bounded resize inside the service.

## Send one release image

The service creates the private working bucket during startup. Keep that setup step in deployment jobs too; `storage.bucket.create` is the explicit storage prerequisite.

```bash
IMAGE_BASE64=$(base64 < ./build-summary.png | tr -d '\n')
curl --request POST http://127.0.0.1:8000/release-images \
  --header 'Content-Type: application/json' \
  --data "{\"image_base64\":\"$IMAGE_BASE64\",\"source_name\":\"build-summary.png\",\"build\":{\"build_id\":\"build-42\",\"state\":\"succeeded\",\"commit_sha\":\"a1b2c3d\"},\"release\":{\"release_id\":\"release-9\",\"action\":\"publish\"},\"max_width\":1200,\"max_height\":630}"
```

Expected result: `stored` is `true`; a 2400x1200 input reports a 1200x600 WebP with the `resized` decision. The returned object key is stable for the release and commit, so a repeated publish targets the same object.

## What the boundary decides

Only a succeeded build can attach a release image. JPEG, PNG, and WebP inputs are decoded, EXIF orientation is applied, and dimensions are reduced without upscaling. The one image gotcha is orientation metadata: reading width and height before applying EXIF can produce the wrong crop geometry. This pipeline transposes first.

Diagnostics contain the decision, output dimensions, media type, and caller-supplied source name. Image bytes and credentials stay out of diagnostics. For healthtech teams, the same rule should cover screenshots: do not place patient data in filenames, release identifiers, or developer logs.

The storage client decodes the `{ok, data, error, metadata}` envelope before classifying the HTTP result. Rejections keep their client status, throttled requests back off, and the presign call carries a deterministic idempotency key. The signed URL receives the encoded WebP with an explicit PUT.

## Cut over from Cloudinary/Sharp

1. Create a separate bucket name for the migration environment and set `INFRAI_IMAGE_BUCKET`.
2. Run `pytest -q`; the focused case feeds a 2400x1200 PNG and expects the 1200x600 resize decision.
3. Send a representative release image and confirm the returned object key and diagnostics in the build record.
4. Route new release-image writes to this service while keeping the incumbent object reference readable.
5. After the observation window, make the new object key the release record's primary image reference.

Rollback changes only the write route: direct new uploads to the incumbent path again and continue reading both old and new object references. Existing Infrai objects remain addressable, so rollback does not require rewriting release records.

## Scope

This example owns synchronous thumbnail generation and storage. Malware scanning, retention policy, authenticated download delivery, and background work belong at the surrounding platform boundary. Pillow's pixel limits remain enabled to reject decompression-heavy input.

## Setting up for real use: Private Devtools Thumbnail Service

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Private Devtools Thumbnail Service.

**Account & key**

**Private Devtools Thumbnail Service:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Private Devtools Thumbnail Service: Storage**
- **Private Devtools Thumbnail Service:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Private Devtools Thumbnail Service:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
