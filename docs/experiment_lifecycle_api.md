# Experiment lifecycle in Swagger

Start the configured API with PostgreSQL, its existing Alembic migration, local
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
   starts as `draft`, with null LS, confidence, and finalization time.
   LS, confidence, and other unsupported JSON fields are rejected with `422`.
4. `POST /evaluations/{evaluation_id}/segmentations`: provide `prompt_type=box`
   and a JSON array in `box`, for example `[2,2,25,20]` for an image containing
   those coordinates. Alternatively use points and labels. Repeat as needed.
5. `POST /evaluations/{evaluation_id}/finalize` with
   `{"clinical_ls": 2, "annotator_confidence": 0.9}`. LS is a required integer
   from 0 to 3. Confidence is optional or null, and otherwise a number from 0 to 1.
   The `200` response contains the finalized evaluation and its timestamp.
6. Further segmentation attempts or a second finalization return `409`.

All evaluation responses include `evaluation_id`, `image_id`, `pci_region_id`,
`annotator_code`, `status`, `clinical_ls`, `annotator_confidence`, `created_at`, and
`finalized_at`. Missing parent records return `404`; invalid fields return `422`.

Finalization means the specialist finished the evaluation and supplied clinical
LS. It does not accept, validate, or select a reference mask. No segmentation
attempt is required before finalization. The system performs no autonomous
diagnosis or automatic LS inference.

## Retrieve persisted resources

`GET /evaluations/{evaluation_id}` returns `200` with the existing evaluation
fields listed above, for either a draft or finalized evaluation. Finalized
responses include the persisted clinical LS, optional confidence, and finalization
timestamp. No nested resources or segmentation attempts are included.
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

These operations reuse the current schema and require no migration. They support
retrieval from persisted state without retaining the original browser File.
Segmentation-attempt retrieval and frontend resume behavior remain outside this
iteration. Image bytes are read into memory; streaming, range requests, retries,
and storage repair are not implemented.

## Image storage and transactions

Uploads reuse the stateless endpoint's content-type, static-frame, byte-size,
dimension, and RGB decoding validation. Invalid uploads return `413`, `415`, or
`422` and create no image record or file. Original bytes are stored without
resizing or recompression, using UUID keys with `.jpg` or `.png` suffixes.
SHA-256 is computed from those exact bytes. Original filenames are discarded.

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
