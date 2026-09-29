# Handoff — 2026-09-29 (Codex)

T-206 / F-019 is now verified with the real image-conditioned Shap-E model inside the
project Docker stack.

- Started the stack with
  `docker compose -f infra/docker-compose.yml --env-file .env up -d --build --wait`;
  API, PostgreSQL, Redis and S3 mock were healthy and the worker was running. The existing,
  complete `.env` was left unchanged.
- The isolated live test passed at the default detailed profile: **32 Karras steps**.
  The exact successful invocation was:

  ```bash
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.ci.yml \
    --env-file .env run --rm \
    -e RECONSTRUCTION_PROVIDER=shap_e -e SOVA_RUN_SHAP_E_LIVE=1 \
    -v physical-ai_shap_e_cache:/app/worker/shap_e_model_cache \
    api-tests uv run --no-sync pytest -vv -s \
    /app/worker/tests/test_reconstruct_photo_live.py::test_a_photo_becomes_a_real_solid_mesh
  ```

- Result: `1 passed in 410.91s (0:06:50)`; shell wall time was 413.239 s with a warm model
  cache. The first cold-cache pass took about 22 minutes including checkpoint downloads.
- Host/container resources: 8 CPUs, 15.61 GiB RAM available to Docker. Sampling sustained
  about 698-790% CPU; warm-run memory samples were 2.82-2.92 GiB, and the cold-load peak
  observed by `docker stats` was 4.08 GiB. No swap use or OOM occurred, so the 16-step
  fallback was not needed.
- This was not the stub path: the live child process was
  `python -I -m worker.shap_e_child image ... 32`, and the persistent
  `physical-ai_shap_e_cache` volume contains the real checkpoints (`ViT-L-14.pt`
  932,768,134 bytes, `image_cond.pt` 1,263,925,407 bytes, `vector_decoder.pt`
  905,199,688 bytes; 2.9 GiB total). The opt-in test then loaded the emitted STL and proved
  it had non-empty vertices/faces, a longest extent of 80 mm, and a z=0 base.

No product-code bug was found and no code commit was needed. The Docker stack remains up;
the checkpoint cache remains in its named volume for subsequent live runs.
