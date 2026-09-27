"""Small regressions for the memory-sensitive Shap-E sandbox child."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import torch

from worker.shap_e_child import _drop_unused_clip_tower, _precompute_conditioning


class _Tower(torch.nn.Module):
    def __init__(self, elements: int) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(elements))


class _ConditionedModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        clip_model = torch.nn.Module()
        clip_model.visual = _Tower(11)
        clip_model.transformer = _Tower(7)
        clip_model.token_embedding = _Tower(5)
        self.clip = SimpleNamespace(model=SimpleNamespace(clip_model=clip_model))

    def cached_model_kwargs(
        self, batch_size: int, model_kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        assert batch_size == 1 and "texts" in model_kwargs
        return {"embeddings": torch.ones(1, 3)}


class _SplitWrapper(torch.nn.Module):
    def __init__(self, wrapped: _ConditionedModel) -> None:
        super().__init__()
        self.wrapped = wrapped
        self.cached_model_kwargs = wrapped.cached_model_kwargs


def test_text_conditioning_is_cached_before_wrapped_clip_vision_tower_is_released() -> None:
    inner = _ConditionedModel()
    model = _SplitWrapper(inner)

    cached = _precompute_conditioning(model, {"texts": ["an owl"]})
    released = _drop_unused_clip_tower(model, "text")

    assert cached["embeddings"].tolist() == [[1.0, 1.0, 1.0]]
    assert model.cached_model_kwargs(1, cached) is cached
    assert inner.clip.model.clip_model.visual is None
    assert released == 11 * torch.tensor(0.0).element_size()
    assert inner.clip.model.clip_model.transformer is not None


def test_image_generation_releases_only_the_text_tower() -> None:
    model = _ConditionedModel()

    released = _drop_unused_clip_tower(model, "image")

    assert released == (7 + 5) * torch.tensor(0.0).element_size()
    assert model.clip.model.clip_model.visual is not None
    assert model.clip.model.clip_model.transformer is None
    assert model.clip.model.clip_model.token_embedding is None
