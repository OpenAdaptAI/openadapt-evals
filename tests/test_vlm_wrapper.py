"""Tests for VLMModelWrapper — multimodal TRL compatibility layer.

Verifies that the wrapper:
1. Injects cached pixel_values into forward() when TRL omits them
2. Passes through pixel_values when already present
3. Delegates generate() and attribute access to the wrapped model
4. Logs appropriately on cache hits and misses
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from openadapt_evals.training.vlm_wrapper import VLMModelWrapper


class _FakeOutput:
    def __init__(self, logits):
        self.logits = logits


class _FakeModel:
    """Minimal model that records what it receives."""

    def __init__(self):
        self.last_forward_kwargs = {}
        self.config = MagicMock(name="config")
        self._params = [MagicMock(name="param")]

    def __call__(self, input_ids=None, **kwargs):
        self.last_forward_kwargs = {"input_ids": input_ids, **kwargs}
        return _FakeOutput(logits="fake_logits")

    def generate(self, **kwargs):
        return "generated_text"

    def parameters(self):
        return self._params


class TestVLMModelWrapper:

    def test_forward_injects_cached_pixel_values(self):
        """TRL calls forward(input_ids=...) — wrapper injects cached vision."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        # Simulate rollout: cache vision inputs
        wrapper.cache_vision_inputs({
            "pixel_values": "fake_pv",
            "image_grid_thw": "fake_thw",
        })

        # Simulate TRL: forward without pixel_values
        wrapper.forward(input_ids="fake_ids")

        assert model.last_forward_kwargs["pixel_values"] == "fake_pv"
        assert model.last_forward_kwargs["image_grid_thw"] == "fake_thw"

    def test_forward_does_not_override_existing_pixel_values(self):
        """If caller passes pixel_values, don't override with cache."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        wrapper.cache_vision_inputs({"pixel_values": "cached_pv"})

        # Caller explicitly passes pixel_values
        wrapper.forward(input_ids="fake_ids", pixel_values="explicit_pv")

        assert model.last_forward_kwargs["pixel_values"] == "explicit_pv"

    def test_forward_without_cache_warns(self, caplog):
        """Forward without cache logs a warning on second call."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        import logging
        with caplog.at_level(logging.WARNING):
            # First call increments miss counter to 1, triggering the warning
            wrapper.forward(input_ids="fake_ids")

        assert "no cached vision inputs" in caplog.text.lower()

    def test_generate_delegates_to_model(self):
        """generate() passes through to the wrapped model."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        result = wrapper.generate(input_ids="test", max_new_tokens=100)
        assert result == "generated_text"

    def test_attribute_delegation(self):
        """Attributes are delegated to the wrapped model."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        assert wrapper.config == model.config
        assert wrapper.parameters() == model._params

    def test_call_routes_to_forward(self):
        """__call__ routes to forward()."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        wrapper.cache_vision_inputs({"pixel_values": "pv"})
        wrapper(input_ids="ids")

        assert model.last_forward_kwargs["pixel_values"] == "pv"

    def test_cache_overwrites_previous(self):
        """Caching new inputs replaces the old cache."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        wrapper.cache_vision_inputs({"pixel_values": "old_pv"})
        wrapper.cache_vision_inputs({"pixel_values": "new_pv"})

        wrapper.forward(input_ids="ids")
        assert model.last_forward_kwargs["pixel_values"] == "new_pv"

    def test_cache_ignores_non_vision_keys(self):
        """Only pixel_values and image_grid_thw are cached."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        wrapper.cache_vision_inputs({
            "pixel_values": "pv",
            "input_ids": "should_not_cache",
            "attention_mask": "should_not_cache",
        })

        wrapper.forward(input_ids="ids")
        assert model.last_forward_kwargs["pixel_values"] == "pv"
        assert "attention_mask" not in model.last_forward_kwargs

    def test_empty_cache_from_text_only_inputs(self):
        """Processor output without images produces empty cache."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        wrapper.cache_vision_inputs({"input_ids": "only_text"})
        # Cache is None (no vision keys) — forward logs warning
        wrapper.forward(input_ids="ids")
        assert "pixel_values" not in model.last_forward_kwargs
