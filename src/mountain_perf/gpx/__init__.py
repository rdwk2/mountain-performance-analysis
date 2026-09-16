"""Lecture GPX et construction du profil horizontal (M2)."""

from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    ProfileBuildResult,
    ProfileError,
    build_profile,
    build_profile_with_diagnostics,
)
from mountain_perf.gpx.reader import GpxError, GpxReadResult, read_gpx

__all__ = [
    "PROFILE_PARAMETER_SPECS",
    "GpxError",
    "GpxReadResult",
    "ProfileBuildResult",
    "ProfileError",
    "build_profile",
    "build_profile_with_diagnostics",
    "read_gpx",
]
