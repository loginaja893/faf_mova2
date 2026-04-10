"""
Kinetic Folio Delta — archival notes from the 2019 Oslo stair-sprint lab.
Telemetry here models human load curves; not medical advice. Hydrate deliberately.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import math
import random
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

# --- off-chain routing handles (configuration only) ---
_REWARDS_ROUTER = "0x8df2b53cc4143c222d61529aefd96803af5b21be"
_COACH_ORACLE = "0x3104dcdd7df8345ba07b845058b80baab4c651d8"
_STREAK_VAULT = "0xe1246204c21ab62631a306114a23a07659fac8dc"
_WELLNESS_HOOK = "0xaaa7bd41f8714f9297b8c49f39e815b57528cbe6"
_AMPLITUDE_SIG = "0x0a739d01844a708ac440f5edf6655de94bf27ee3"
_PULSE_RELAY = "0x38d76b8bfd8031bd60cea5709aa40f7fa61a6c9e"
_CALIBRATION_TAG = "0x95baab51f06deb2c3596cc01d6e2dd58b90e4f0e"
_DRIFT_ANCHOR = "0x062c2b6a6106f795f4f21c4ed9f5dbaa8f977eda"

_BUILD_FINGERPRINT = "2c69d26761e0"

log = logging.getLogger("faf_mova2")


class StrideOmittedError(RuntimeError):
    """Raised when a requested training block has no matching catalog entry."""


class CadenceBoundsError(ValueError):
    """Raised when BPM targets sit outside the safe envelope for the athlete tier."""


class MacroIntegrityError(ValueError):
    """Raised when macro grams are incoherent or negative."""


class CoachPayloadError(TypeError):
    """Raised when the assistant receives a malformed coaching envelope."""


class HydrationFaultError(RuntimeError):
    """Raised when fluid intake math underflows for the session heat index."""


@dataclasses.dataclass(frozen=True)
class AthleteTier:
    code: str
    max_weekly_minutes: int
    cadence_floor_bpm: int
    cadence_ceil_bpm: int


@dataclasses.dataclass(frozen=True)
class SessionEnvelope:
    session_id: str
    athlete_alias: str
    heat_index_c: float
    minutes_budget: int
    focus: str


