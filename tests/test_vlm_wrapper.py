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

    def test_peft_attributes_delegated(self):
        """PEFT attributes are accessible through the wrapper."""
        model = _FakeModel()
        model.peft_config = {"default": "lora_config"}
        model.active_adapter = "default"
        wrapper = VLMModelWrapper(model)

        assert wrapper.peft_config == {"default": "lora_config"}
        assert wrapper.active_adapter == "default"

    def test_hasattr_peft_config(self):
        """hasattr(wrapper, 'peft_config') returns True when model has it."""
        model = _FakeModel()
        model.peft_config = {"default": "config"}
        wrapper = VLMModelWrapper(model)

        assert hasattr(wrapper, "peft_config"), (
            "hasattr(wrapper, 'peft_config') must return True for TRL's "
            "validate_quantization_for_training() to pass."
        )

    def test_hasattr_peft_config_false_when_missing(self):
        """hasattr(wrapper, 'peft_config') returns False when model lacks it."""
        model = _FakeModel()
        wrapper = VLMModelWrapper(model)

        assert not hasattr(wrapper, "peft_config")

    def test_isinstance_peft_model(self):
        """isinstance(wrapper, PeftModel) works when PEFT is available."""
        try:
            from peft import PeftModel
        except ImportError:
            pytest.skip("peft not installed")

        # Create a mock that isinstance recognizes as PeftModel
        model = MagicMock(spec=PeftModel)
        model.peft_config = {"default": "config"}
        wrapper = VLMModelWrapper(model)

        assert isinstance(wrapper, PeftModel), (
            "isinstance(wrapper, PeftModel) must return True. "
            "TRL's validation uses isinstance to detect PEFT adapters. "
            "Without this, TRL rejects quantized models."
        )


# ---------------------------------------------------------------------------
# Real e2e test with a tiny torch model (requires torch — skipped in CI)
# ---------------------------------------------------------------------------


@pytest.mark.heavy
class TestVLMModelWrapperE2E:
    """End-to-end test with real torch tensors.

    Verifies that cached pixel_values flow through the wrapper's forward
    pass and produce different logits than a blind forward (no images).
    Requires torch — skipped in CI via @pytest.mark.heavy.
    """

    @staticmethod
    def _make_tiny_vlm():
        """Build a minimal VLM that uses pixel_values in its forward pass."""
        torch = pytest.importorskip("torch")
        import torch.nn as nn

        class TinyVLM(nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = nn.Embedding(100, 16)
                self.vision_proj = nn.Linear(3, 16)
                self.head = nn.Linear(16, 100)

            def forward(self, input_ids, pixel_values=None, **kwargs):
                h = self.embed(input_ids)
                if pixel_values is not None:
                    # Add vision signal to the first position
                    vis = self.vision_proj(pixel_values.mean(dim=(-2, -1)))
                    h[:, 0, :] += vis.unsqueeze(1).squeeze(1)
                logits = self.head(h)

                class Out:
                    pass
                out = Out()
                out.logits = logits
                return out

            def generate(self, **kwargs):
                return self(kwargs["input_ids"], pixel_values=kwargs.get("pixel_values"))

        return TinyVLM()

    def test_forward_with_cached_pixel_values_changes_logits(self):
        """Cached pixel_values produce different logits than blind forward."""
        torch = pytest.importorskip("torch")
        model = self._make_tiny_vlm()
        wrapper = VLMModelWrapper(model)

        input_ids = torch.tensor([[1, 2, 3, 4, 5]])
        pixel_values = torch.randn(1, 3, 10, 10)

        # Forward WITHOUT vision (blind)
        out_blind = wrapper.forward(input_ids=input_ids)
        logits_blind = out_blind.logits.detach().clone()

        # Cache vision inputs
        wrapper.cache_vision_inputs({"pixel_values": pixel_values})

        # Forward WITH cached vision (TRL's training step)
        out_vision = wrapper.forward(input_ids=input_ids)
        logits_vision = out_vision.logits.detach()

        # Logits should be different when vision is present
        assert not torch.allclose(logits_blind, logits_vision, atol=1e-6), (
            "Logits with cached pixel_values should differ from blind logits. "
            "If they're the same, the wrapper isn't injecting vision inputs."
        )

    def test_cache_survives_multiple_forward_calls(self):
        """Cached pixel_values are reused across multiple forward calls."""
        torch = pytest.importorskip("torch")
        model = self._make_tiny_vlm()
        wrapper = VLMModelWrapper(model)

        input_ids = torch.tensor([[1, 2, 3]])
        pixel_values = torch.randn(1, 3, 10, 10)
        wrapper.cache_vision_inputs({"pixel_values": pixel_values})

        out1 = wrapper.forward(input_ids=input_ids)
        out2 = wrapper.forward(input_ids=input_ids)

        # Both should get the same vision-augmented logits
        assert torch.allclose(out1.logits, out2.logits, atol=1e-6)
