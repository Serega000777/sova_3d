# Demos (E12)

Runnable walkthroughs of the two paths the product promises. They talk to a running stack
over the public API — the same calls the web and mobile clients make — and print what a
user would see at each step, so they double as end-to-end checks after a change.

```bash
docker compose -f infra/docker-compose.yml up -d
python demos/organizer_from_text.py     # T-098
python demos/scan_to_model.py           # T-099
python demos/export_validated.py        # T-100
```

With no arguments each demo creates a **new** user and workspace through the API
container's CLI, so "new user" means new. Pass `--token`/`--workspace` to reuse one.

## `organizer_from_text.py` — a sentence becomes an editable model (T-098)

A Russian prompt ("Органайзер 200×100×50 мм с 6 секциями, скругление 1.5 мм") →  a typed
plan → the OCCT kernel → a version. Then the part a demo usually skips: the model is
**edited** — 180 mm wide, by the numbers — which creates a second version without touching
the first, checked for printability, and exported as STL.

If the planner needs a dimension it does not have, the demo stops and asks you, because
that is what the product does instead of guessing.

## `scan_to_model.py` — an object becomes a model (T-099)

The mobile path with generated frames, so it runs without a camera: session → frames one
at a time (including a re-sent frame, to show that a dropped connection does not
duplicate) → finalize → reconstruction → the report a user reads before deciding →
accept → a normal project version, then a print check.

The report states the size **and where the size came from**: a depth sensor, a number the
user gave, or an assumption. Without a depth sensor and without a measurement it says so.

## `export_validated.py` — a model becomes a printable file (T-100)

Import or build, validate, repair if needed, export STL/3MF/GLB with the printable gate
on, and download the result.

## Notes

- Reconstruction uses the local stub provider unless one is configured; its report says
  `placeholder: true` so a demo can never be mistaken for a photogrammetry result.
- Every demo prints the token and workspace it used, so you can open the same project in
  the web app at <http://localhost:3100>.
