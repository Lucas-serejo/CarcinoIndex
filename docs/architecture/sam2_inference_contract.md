**Language:** English · [Português](sam2_inference_contract.pt-BR.md)

# SAM 2.1 inference contract in the M3 API

This document describes the implemented boundary between the AI module
validated up to M2.5 and the experimental M3 API.

## Model instance

SAM 2.1 Hiera Small is expensive to load. The lifespan creates a single
`SAM2Segmenter` instance, calls `load()` once at startup and reuses the model
across inferences. On shutdown, it calls `close()`.

The checkpoint remains external to CarcinoIndex, and the configuration remains
the logical identifier `configs/sam2.1/sam2.1_hiera_s.yaml`.

## Predictor state

The official predictor keeps the embedding and shape of the current image.
Consequently:

- `set_image()` followed by `segment_with_box()` or `segment_with_points()` is
  suitable for notebooks and interactive refinement;
- these calls are not safe for concurrent execution on the same instance;
- `infer()` represents one logical `set → predict → clear` unit and clears the
  transient state on success or failure;
- `infer()` does not implement synchronization and also needs mutual exclusion
  when the instance is shared.

## Strategy implemented in M3

- `SegmentationService` holds one `SAM2Segmenter` instance.
- The service, not the endpoint, is responsible for the model lifecycle.
- A service lock covers the complete call to `infer()`.
- The model is loaded at startup/lifespan.
- `close()` runs on shutdown.
- The endpoint never accesses the official predictor directly.
- The endpoint depends on the application service and handles only the HTTP
  contract.

The service uses an `asyncio.Lock` that fully covers
`await asyncio.to_thread(segmenter.infer, image, prompt)`. The wrapper itself
has no lock. At this stage the application must run with exactly one worker and
accepts one inference at a time.

## Current HTTP contract

The expected flow is:

1. the HTTP layer accepts only static JPEG or PNG and validates bytes,
   dimensions and pixels;
2. the image is decoded and explicitly converted to an RGB `np.ndarray`;
3. the HTTP prompt is converted to `BoxPrompt` or `PointsPrompt`;
4. the service acquires the lock and calls `SAM2Segmenter.infer()`;
5. `SegmentationResult.to_metadata_dict()` provides serializable metadata;
6. the boolean mask is encoded as a Base64 PNG, separate from the metadata.

`to_metadata_dict()` does not include masks, logits, personal paths or image
content. In the stateless route, image, mask and prompt are not persisted. The
attempts route reuses the service and lock and persists masks and prompts; see
[experimental persistence](experiment_persistence.md). The `selected_score`
field remains an internal estimate of the quality of the mask produced by SAM 2
and does not represent clinical confidence, diagnosis or cancer probability.

## Currently out of scope

- inference queue;
- multiple GPUs;
- multiple workers;
- RLE;
- authentication;
- LS classification;
- video tracking;
- fine-tuning.
