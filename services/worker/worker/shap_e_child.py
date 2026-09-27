"""Sandbox entry point for Shap-E: a photo (F-019) or a text prompt (F-001) to a raw mesh.

    python -m worker.shap_e_child image <photo> <out_dir> <cache_dir>
    python -m worker.shap_e_child text <prompt> <out_dir> <cache_dir>

An untrusted photo or prompt goes in, a raw mesh comes out in whatever internal scale and
orientation the model happens to use — rescaling, orienting and everything else that
belongs to platform policy stays on the parent side (`worker.reconstruction`,
`worker.generate_mesh`). This script's only job is turning pixels or words into geometry,
on CPU, offline once the checkpoints are cached.

`shap_e.util.notebooks.decode_latent_mesh` would do the mesh decode in three lines, but
that module imports `ipywidgets` at the top purely for its (unused, here) `gif_widget`
helper — a notebook-only dependency this worker has no reason to carry. `_decode_mesh`
below is that function's actual body, copied rather than imported.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, cast

MIN_KARRAS_STEPS = 8
MAX_KARRAS_STEPS = 64


def _decode_mesh(xm: Any, latent: Any) -> Any:
    import numpy as np
    import torch
    from shap_e.models.nn.camera import DifferentiableCameraBatch, DifferentiableProjectiveCamera
    from shap_e.util.collections import AttrDict

    def pan_cameras(size: int, device: torch.device) -> DifferentiableCameraBatch:
        origins, xs, ys, zs = [], [], [], []
        for theta in np.linspace(0, 2 * np.pi, num=20):
            z = np.array([np.sin(theta), np.cos(theta), -0.5])
            z /= np.sqrt(np.sum(z**2))
            origin = -z * 4
            x = np.array([np.cos(theta), -np.sin(theta), 0.0])
            y = np.cross(z, x)
            origins.append(origin)
            xs.append(x)
            ys.append(y)
            zs.append(z)
        return DifferentiableCameraBatch(
            shape=(1, len(xs)),
            flat_camera=DifferentiableProjectiveCamera(
                origin=torch.from_numpy(np.stack(origins, axis=0)).float().to(device),
                x=torch.from_numpy(np.stack(xs, axis=0)).float().to(device),
                y=torch.from_numpy(np.stack(ys, axis=0)).float().to(device),
                z=torch.from_numpy(np.stack(zs, axis=0)).float().to(device),
                width=size,
                height=size,
                x_fov=0.7,
                y_fov=0.7,
            ),
        )

    with torch.no_grad():
        decoded = xm.renderer.render_views(
            AttrDict(cameras=pan_cameras(2, latent.device)),  # lowest resolution possible
            # the decoder-only checkpoint is its own bottleneck; a full transmitter keeps
            # it in the encoder (the same switch shap_e.util.notebooks makes)
            params=getattr(xm, "encoder", xm).bottleneck_to_params(latent[None]),
            options=AttrDict(rendering_mode="stf", render_with_direction=False),
        )
    return decoded.raw_meshes[0]


def _load(name: str, device: Any, cache: str) -> Any:
    """shap_e's load_model, minus its second copy of the weights: the checkpoint is
    memory-mapped and assigned into the model instead of copied over its parameters."""
    import torch
    from shap_e.models.configs import model_from_config
    from shap_e.models.download import MODEL_PATHS, fetch_file_cached, load_config

    model = model_from_config(load_config(name, cache_dir=cache), device=device)
    path = fetch_file_cached(MODEL_PATHS[name], progress=False, cache_dir=cache)
    try:
        state = torch.load(path, map_location=device, mmap=True, weights_only=True)
    except RuntimeError:  # a checkpoint in the legacy (non-zip) format cannot be mapped
        state = torch.load(path, map_location=device, weights_only=True)
    model.load_state_dict(state, assign=True)
    return model.eval()


def _precompute_conditioning(
    model: Any, model_kwargs: dict[str, Any], *, batch_size: int = 1
) -> dict[str, Any]:
    """Turn the source image/text into its small CLIP embedding exactly once.

    ``sample_latents`` normally performs this cache step itself.  We do it before
    pruning CLIP so the heavyweight modality towers are no longer needed during
    the hour-long CPU diffusion pass.  Replacing the cache hook with an identity
    also matters for image300M: its hook only accepts ``images`` and would try to
    encode the already-cached ``embeddings`` a second time.
    """
    cache = getattr(model, "cached_model_kwargs", None)
    if not callable(cache):
        return model_kwargs
    cached = cast(dict[str, Any], cache(batch_size, model_kwargs))
    model.cached_model_kwargs = lambda _batch_size, kwargs: kwargs
    return cached


def _clip_model_from(model: Any) -> Any | None:
    """Find OpenAI CLIP through Shap-E's optional SplitVectorDiffusion wrapper."""
    current = model
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        clip = getattr(current, "clip", None)
        clip_model = getattr(getattr(clip, "model", clip), "clip_model", None)
        if clip_model is not None:
            return clip_model
        current = getattr(current, "wrapped", None)
    return None


def _module_bytes(module: Any) -> int:
    if module is None or not hasattr(module, "parameters"):
        return 0
    tensors = [*module.parameters(), *module.buffers()]
    return sum(int(t.numel() * t.element_size()) for t in tensors)


def _drop_unused_clip_tower(model: Any, mode: str) -> int:
    """A text prompt never looks at CLIP's image tower, a photo never at its text tower —
    together they are over a gigabyte a small Docker VM cannot spare."""
    clip_model = _clip_model_from(model)
    if clip_model is None:
        return 0
    unused = ("visual",) if mode == "text" else ("transformer", "token_embedding")
    released = 0
    for part in unused:
        value = getattr(clip_model, part, None)
        if value is not None:
            released += _module_bytes(value)
            setattr(clip_model, part, None)
    return released


MODES = {"image": "image300M", "text": "text300M"}
GUIDANCE = {"image": 3.0, "text": 15.0}  # the values Shap-E's own examples use


def main(args: list[str]) -> int:
    if len(args) != 5 or args[0] not in MODES:
        print(
            json.dumps(
                {"ok": False, "message": "expected image|text, source, out dir, cache, steps"}
            )
        )
        return 2
    mode, source, out_dir, cache = args[0], args[1], Path(args[2]), args[3]
    try:
        karras_steps = int(args[4])
        if not MIN_KARRAS_STEPS <= karras_steps <= MAX_KARRAS_STEPS:
            raise ValueError(
                f"steps must be between {MIN_KARRAS_STEPS} and {MAX_KARRAS_STEPS}"
            )
        import torch
        import trimesh
        from PIL import Image
        from shap_e.diffusion.gaussian_diffusion import diffusion_from_config
        from shap_e.diffusion.sample import sample_latents
        from shap_e.models.download import load_config

        # shap_e puts CLIP's weights in <cwd>/shap_e_model_cache whatever cache_dir says;
        # from the cache's parent that is the cache itself (a persistent volume in Docker)
        os.chdir(Path(cache).parent)
        device = torch.device("cpu")
        torch.set_grad_enabled(False)  # inference only: no autograd graph to keep in memory
        # One model in memory at a time (the conditional model samples, then goes; the
        # decoder decodes): the Docker VM has 3.6 GB, and all of it at once OOM-killed us.
        model = _load(MODES[mode], device, cache)
        if mode == "image":
            # shap_e.util.image_util.load_image routes through `blobfile`, which does not
            # recognise a plain local path on every platform; a real file on disk needs no
            # cloud-storage abstraction, so PIL reads it directly.
            with Image.open(source) as opened:
                model_kwargs: dict[str, Any] = {"images": [opened.convert("RGB")]}
                model_kwargs = _precompute_conditioning(model, model_kwargs)
        else:
            model_kwargs = {"texts": [source]}
            model_kwargs = _precompute_conditioning(model, model_kwargs)
        released_clip_bytes = _drop_unused_clip_tower(model, mode)
        gc.collect()
        diffusion = diffusion_from_config(load_config("diffusion", cache_dir=cache))

        latents = sample_latents(
            batch_size=1,
            model=model,
            diffusion=diffusion,
            guidance_scale=GUIDANCE[mode],
            model_kwargs=model_kwargs,
            progress=False,
            clip_denoised=True,
            use_fp16=False,
            use_karras=True,
            karras_steps=karras_steps,
            sigma_min=1e-3,
            sigma_max=160,
            s_churn=0,
        )
        del model
        gc.collect()
        # latent -> mesh needs only the decoder checkpoint, not the full transmitter
        xm = _load("decoder", device, cache)
        mesh = _decode_mesh(xm, latents[0]).tri_mesh()

        out_dir.mkdir(parents=True, exist_ok=True)
        raw_path = out_dir / "raw.stl"
        built = trimesh.Trimesh(vertices=mesh.verts, faces=mesh.faces, process=False)
        built.export(raw_path)
        print(
            json.dumps(
                {
                    "ok": True,
                    "mesh_path": str(raw_path),
                    "vertices": int(len(built.vertices)),
                    "faces": int(len(built.faces)),
                    "released_clip_bytes": released_clip_bytes,
                    "karras_steps": karras_steps,
                }
            )
        )
    except Exception as exc:  # a child crash must become a structured failure, never a traceback
        # where it broke, without a whole traceback: "EOFError: " alone is undiagnosable
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        where = f" (in {frame.name}, {Path(frame.filename).name}:{frame.lineno})"
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}{where}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
