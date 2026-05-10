"""Canonical AF<->AE handoff surface.

This module exists to prevent caller drift across legacy and contract-compliant
bundle/parser implementations. New AF code should import handoff classes from
here rather than choosing a version-specific module ad hoc.
"""

from .job_bundle_v2 import BatchBundleBuilder, JobBundleBuilder
from .output_parser_v2 import (
    OutputImporter,
    OutputParser,
    map_eater_status_to_finder,
)

__all__ = [
    "BatchBundleBuilder",
    "JobBundleBuilder",
    "OutputImporter",
    "OutputParser",
    "map_eater_status_to_finder",
]
