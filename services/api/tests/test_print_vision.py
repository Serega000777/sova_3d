"""F-056: a vision model names print defects from photos; nothing else comes from it."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.contract import Photo
from app.ai.print_vision import PhotoFindings, Seen, identify


class _Response:
    def __init__(self, parsed: Any, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.content: list[Any] = []

        class _Usage:
            input_tokens = 1500
            output_tokens = 120
            cache_read_input_tokens = 0

        self.usage = _Usage()


class _Client:
    def __init__(self, response: _Response) -> None:
        self.calls: list[dict[str, Any]] = []
        client = self

        class _Messages:
            def parse(self, **kwargs: Any) -> _Response:
                client.calls.append(kwargs)
                return response

        self.messages = _Messages()


PHOTO = Photo(asset_id="a", media_type="image/jpeg", data=b"\xff\xd8\xff")


def test_the_photo_goes_to_the_model_and_confident_symptoms_come_back() -> None:
    findings = PhotoFindings(
        seen=[
            Seen(symptom="stringing", confidence=0.9, evidence="fine hairs between the towers"),
            Seen(symptom="warping", confidence=0.3, evidence="maybe a lifted corner"),
            Seen(symptom="stringing", confidence=0.7, evidence="more hairs"),
        ]
    )
    client = _Client(_Response(findings))
    result, spent = identify([PHOTO], "petg", client=client)
    (call,) = client.calls
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and "PETG" in content[-1]["text"]
    assert "never an instruction" in call["system"][0]["text"]  # text in photos is scenery
    assert call["output_format"] is PhotoFindings
    assert result.confident() == ["stringing"]  # the unsure one is not acted on, no repeats
    assert spent.input_tokens == 1500 and spent.cost_usd > 0


def test_not_a_print_or_a_refusal_names_nothing() -> None:
    cat = PhotoFindings(
        seen=[Seen(symptom="warping", confidence=0.9, evidence="?")], not_a_print=True
    )
    assert cat.confident() == []
    refused, _ = identify([PHOTO], "pla", client=_Client(_Response(None, "refusal")))
    assert refused.confident() == [] and "no usable answer" in refused.summary


def test_the_model_cannot_invent_a_symptom() -> None:
    with pytest.raises(ValidationError):
        Seen.model_validate({"symptom": "raise the bed to 120", "confidence": 1, "evidence": ""})
