#!/usr/bin/env python
"""Thin CLI wrapper for the standalone GRPO trainer.

Usage:
    python scripts/train_grpo_standalone.py \\
        --task-dir example_tasks \\
        --server-url http://localhost:5001 \\
        --model Qwen/Qwen3.5-9B \\
        --num-steps 10 \\
        --output checkpoints/

Or equivalently via module:
    python -m openadapt_evals.training.standalone.trainer --task-dir ...
"""

from openadapt_evals.training.standalone.trainer import main

if __name__ == "__main__":
    main()
