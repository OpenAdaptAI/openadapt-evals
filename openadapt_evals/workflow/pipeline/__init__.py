"""Pipeline stages for workflow extraction.

- match: Cosine similarity matching of workflows to canonical workflows
- (future) transcript: Pass 1 VLM transcript generation
- (future) extract: Pass 2 workflow extraction
- (future) scrub: Pass 0 PII scrubbing
"""

from openadapt_evals.workflow.pipeline.match import (
    SIMILARITY_THRESHOLD,
    add_instance_to_canonical,
    create_canonical_from_workflow,
    match_workflow_to_canonical,
)

__all__ = [
    "SIMILARITY_THRESHOLD",
    "add_instance_to_canonical",
    "create_canonical_from_workflow",
    "match_workflow_to_canonical",
]
