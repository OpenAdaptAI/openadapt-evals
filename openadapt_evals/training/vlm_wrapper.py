"""VLM model wrapper for TRL compatibility.

TRL's GRPOTrainer was designed for text-only LLMs. During the training
step, it calls model.forward(input_ids=...) to recompute logprobs under
the current policy. For multimodal VLMs, this forward pass also needs
pixel_values and image_grid_thw — but TRL doesn't know about them.

This wrapper solves the problem by caching vision inputs during rollout
generation (when we have the images) and injecting them during TRL's
forward pass (when TRL only passes input_ids).

Usage:
    from openadapt_evals.training.vlm_wrapper import VLMModelWrapper

    wrapper = VLMModelWrapper(model)
    trainer = GRPOTrainer(model=wrapper, ...)

    # During rollout generation:
    inputs = processor(text=..., images=[img], return_tensors="pt")
    wrapper.cache_vision_inputs(inputs)
    outputs = wrapper.generate(**inputs, ...)

    # During TRL's training forward pass:
    # TRL calls wrapper.forward(input_ids=...) — we inject cached vision inputs
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VLMModelWrapper:
    """Wraps a VLM so TRL's forward pass gets pixel_values.

    Caches vision tensors (pixel_values, image_grid_thw) during rollout
    generation and injects them during forward passes that lack them.

    This is the standard adapter pattern for making framework-incompatible
    models work with training frameworks. TRL calls model.forward() with
    only input_ids; we intercept and add the vision inputs.
    """

    def __init__(self, model: Any):
        # Store model WITHOUT going through __setattr__ (which delegates to model)
        object.__setattr__(self, "_vlm_model", model)
        object.__setattr__(self, "_vision_cache", None)
        object.__setattr__(self, "_cache_hits", 0)
        object.__setattr__(self, "_cache_misses", 0)

    def cache_vision_inputs(self, inputs: dict[str, Any]) -> None:
        """Cache vision tensors from a processor output dict.

        Call this during rollout generation, right after processor() and
        before generate(). The cached tensors will be injected into
        subsequent forward() calls that lack pixel_values.

        Args:
            inputs: Dict from processor(text=..., images=...) containing
                pixel_values and optionally image_grid_thw.
        """
        cache = {}
        for key in ("pixel_values", "image_grid_thw"):
            if key in inputs:
                # Clone and detach to avoid gradient issues
                val = inputs[key]
                if hasattr(val, "detach"):
                    cache[key] = val.detach().clone()
                else:
                    cache[key] = val
        if cache:
            object.__setattr__(self, "_vision_cache", cache)

    def forward(self, input_ids: Any = None, **kwargs: Any) -> Any:
        """Forward pass with automatic vision input injection.

        If kwargs lacks pixel_values and we have cached vision inputs,
        inject them. This is the key fix: TRL calls model.forward()
        with only input_ids, but VLMs need pixel_values too.
        """
        model = object.__getattribute__(self, "_vlm_model")
        cache = object.__getattribute__(self, "_vision_cache")

        if "pixel_values" not in kwargs and cache is not None:
            for key, val in cache.items():
                if key not in kwargs:
                    # Move to same device as input_ids
                    if hasattr(val, "to") and hasattr(input_ids, "device"):
                        kwargs[key] = val.to(input_ids.device)
                    else:
                        kwargs[key] = val
            hits = object.__getattribute__(self, "_cache_hits")
            object.__setattr__(self, "_cache_hits", hits + 1)
            if hits == 0:
                logger.info(
                    "VLMModelWrapper: injecting cached vision inputs into "
                    "forward pass (keys=%s). This means TRL called forward() "
                    "without pixel_values — the wrapper is working as intended.",
                    list(cache.keys()),
                )
        elif "pixel_values" not in kwargs and cache is None:
            misses = object.__getattribute__(self, "_cache_misses")
            object.__setattr__(self, "_cache_misses", misses + 1)
            if misses == 0:
                logger.warning(
                    "VLMModelWrapper: forward() called without pixel_values "
                    "and no cached vision inputs available. The model is blind. "
                    "Ensure cache_vision_inputs() is called during generation.",
                )

        return model(input_ids=input_ids, **kwargs)

    def generate(self, **kwargs: Any) -> Any:
        """Generate with the underlying model. No interception needed —
        our generate_fn passes pixel_values explicitly."""
        model = object.__getattribute__(self, "_vlm_model")
        return model.generate(**kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Route __call__ to forward for compatibility with TRL."""
        return self.forward(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attribute access to the wrapped model.

        This makes the wrapper transparent: trainer.model.config,
        trainer.model.parameters(), etc. all work as expected.
        """
        model = object.__getattribute__(self, "_vlm_model")
        return getattr(model, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate attribute setting to the wrapped model."""
        model = object.__getattribute__(self, "_vlm_model")
        setattr(model, name, value)
