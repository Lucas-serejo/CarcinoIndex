# Experiment lifecycle in Swagger

Start the configured API with PostgreSQL, Alembic migrations through `0002_segmentation_review`, local
storage, and SAM available as described in the backend README. Open `/docs`.
All paths below use the default `/api/v1` prefix.

1. `POST /cases` with `{"anonymous_patient_code": "PATIENT-001"}`.
   Copy `case_id` from the `201` response. Codes are pseudonymous identifiers,
   trimmed, nonblank, and limited to 128 characters. Duplicates are allowed.
   Supply no names, medical record numbers, CPF, email, or other personal data.
2. `POST /cases/{case_id}/images`: select a JPEG or PNG in the multipart `image`
   field. Copy `image_id` from the `201` response. The response includes `case_id`,
   width, height, SHA-256, and creation time, without filenames or storage paths.
3. `POST /images/{image_id}/evaluations` with
   `{"pci_region_id": 6, "annotator_code": "MED01"}`. Copy `evaluation_id` from
   the `201` response. Region IDs range from 0 through 12. The specialist code
   is pseudonymous, nonblank, and limited to 128 characters. The evaluation
   starts as `draft`, with null LS, confidence, reviewed attempt ID, segmentation
   quality, and finalization time.
   LS, confidence, and other unsupported JSON fields are rejected with `422`.
4. `POST /evaluations/{evaluation_id}/segmentations`: provide `prompt_type=box`
   and a JSON array in `box`, for example `[2,2,25,20]` for an image containing
   those coordinates. Alternatively use points and labels. Repeat as needed.
   While viewing the mask, the specialist chooses `adequate`, `partially_adequate`,
   or `inadequate`. Retain the `attempt_id` of that specific reviewed result.
5. `POST /evaluations/{evaluation_id}/finalize` with
   `{"clinical_ls": 2, "annotator_confidence": 0.9, "reviewed_attempt_id": "<attempt UUID>", "segmentation_quality": "adequate"}`.
   LS is a required integer from 0 to 3. Confidence is optional or null, and otherwise
   a number from 0 to 1 representing the specialist's confidence in clinical LS.
   Both review fields are required and non-null for every new API finalization.
   Quality accepts only the three exact values above; extra fields remain forbidden.
   The `200` response contains the finalized evaluation and its timestamp.
6. Further segmentation attempts or a second finalization return `409`.

All evaluation responses include `evaluation_id`, `image_id`, `pci_region_id`,
`annotator_code`, `status`, `clinical_ls`, `annotator_confidence`, `reviewed_attempt_id`,
`segmentation_quality`, `created_at`, and `finalized_at`. Missing parent records return
`404`; invalid fields return `422`. A missing attempt or an attempt belonging to another
Evaluation returns `422` with `{"error":{"code":"invalid_segmentation_review","message":"Reviewed attempt must belong to this evaluation."}}`.
The failed request leaves the draft unchanged. Existing finalized records without
review fields remain readable with both fields null.

Finalization means the specialist finished the evaluation and supplied clinical
LS and a qualitative judgment tied to a specific segmentation attempt. That judgment
is not clinical validation, LS, SAM confidence, or ground truth. No mask is accepted,
validated, or transformed into a reference. The specialist supplies PCI region and
LS; the workflow does not calculate the complete PCI or perform autonomous diagnosis.
SAM `selected_score` retains only its internal quality/ranking meaning.

## Retrieve persisted resources

`GET /evaluations/{evaluation_id}` returns `200` with the existing evaluation
fields listed above, for either a draft or finalized evaluation. Finalized
responses include the persisted clinical LS, optional confidence, reviewed attempt ID,
segmentation quality, and finalization timestamp. No nested resources or segmentation attempts are included.
A missing evaluation returns `404` with
`{"error":{"code":"evaluation_not_found","message":"Evaluation not found."}}`.

`GET /images/{image_id}/content` returns `200` with the exact original validated
JPEG or PNG bytes for the persisted experimental workflow. It performs no resizing,
recompression, transcoding, or base64 conversion. Content-Type is `image/png` for
`.png` storage keys and `image/jpeg` for `.jpg` or `.jpeg` keys. These are internal,
application-generated keys; filenames, storage keys, and filesystem paths are not
exposed through response metadata. No Content-Disposition filename is set.
Successful image responses carry `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`, locally scoped to this endpoint.

A missing image database record returns `404` with
`{"error":{"code":"image_not_found","message":"Image not found."}}`.
If the record exists but its content is missing, inaccessible, or has an invalid
internal storage key, the response is `500` with
`{"error":{"code":"image_content_unavailable","message":"Stored image content is unavailable."}}`.
Storage errors expose no keys, paths, or exception details. The database session
closes before `LocalStorage.read()` retrieves the bytes.

Apply `python -m alembic upgrade head` before using the extended Evaluation contract.
The retrieval operations support
retrieval from persisted state without retaining the original browser File.
Segmentation-attempt retrieval and frontend resume behavior remain outside this
iteration. Image bytes are read into memory; streaming, range requests, retries,
and storage repair are not implemented.

## Image storage and transactions

Uploads reuse the stateless endpoint's content-type, static-frame, byte-size,
dimension, orientation, and RGB decoding validation. Invalid uploads return
`413`, `415`, or `422` and create no image record or file. Original bytes are stored without
resizing or recompression, using UUID keys with `.jpg` or `.png` suffixes.
SHA-256 is computed from those exact bytes. Original filenames are discarded.

JPEG and PNG may both carry EXIF orientation metadata. The shared decoder accepts
absent orientation or normal Orientation `1`, and rejects Orientation `2` through `8`,
unsupported values/types, and malformed metadata that cannot be safely interpreted:

```json
{"error":{"code":"unsupported_image_orientation","message":"Image orientation metadata is unsupported or invalid. Normalize image orientation before upload."}}
```

The response is HTTP `422`. Normalize orientation before upload; the backend
never rotates or transposes images and never creates a normalized copy. Preserving
unchanged bytes while rejecting display transformations keeps browser prompt
coordinates aligned with SAM pixels. This applies to `POST /cases/{case_id}/images`
and stateless `POST /segmentations`. `POST /evaluations/{evaluation_id}/segmentations`
also revalidates stored bytes before inference. Previously stored files are not
rewritten or audited by a migration, and the content retrieval endpoint continues
to return their original bytes.

The case lookup finishes before upload validation. Storage occurs before the
short database write transaction. If persistence or commit raises, only the new
file is deleted. Errors returned by the API contain no internal exception details.
As with existing mask storage, process interruption, cleanup filesystem failure,
or an uncertain commit outcome cannot be made atomic across PostgreSQL and the
filesystem. There are no retries or background cleanup workers.

## Tests

Configure `TEST_DATABASE_URL` to a disposable PostgreSQL database using the
`postgresql+psycopg` driver and run:

```powershell
python -m pytest tests/app/api/test_experiment.py -q -ra
python -m pytest -q -ra
```

Each PostgreSQL test uses the existing fixture's isolated random schema and real
temporary LocalStorage. The complete HTTP lifecycle test uses fake SAM and needs
no CUDA. PostgreSQL tests skip when `TEST_DATABASE_URL` is absent; connection
failures are errors when it is set. Existing CI supplies PostgreSQL.
