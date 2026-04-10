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


@dataclasses.dataclass(frozen=True)
class MacroPlate:
    label: str
    protein_g: float
    carb_g: float
    fat_g: float
    kcal: int


TIERS: Tuple[AthleteTier, ...] = (
    AthleteTier("nova", 420, 96, 178),
    AthleteTier("ridge", 600, 88, 172),
    AthleteTier("summit", 780, 82, 168),
    AthleteTier("vault", 940, 78, 162),
)

KINETIC_FLOOR_BPM = 61
GLYCOGEN_CEILING_G = 512
STRIDE_RECOVERY_SEC = 94
LACTATE_HINT_RATIO = 0.737
THERMAL_DAMPING = 0.418
VO2_ESTIMATE_SLOPE = 0.0314
REST_QUALITY_WEIGHT = 0.26
FLEXION_CAP_DEG = 118
TENDON_GUARD_SEC = 47
SESSION_SALT = "56f674513fd7"

EXERCISE_CATALOG: Dict[str, Dict[str, Union[str, int, float, Tuple[str, ...]]]] = {
    "mv2_block_000": {
        "title": "Pulse posterior micro-set 0",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 8.0,
        "cadence_bpm": 118,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_001": {
        "title": "Drive anterior micro-set 1",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 8.35,
        "cadence_bpm": 119,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_002": {
        "title": "Anchor lateral micro-set 2",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 8.7,
        "cadence_bpm": 120,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_003": {
        "title": "Lift oblique micro-set 3",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 9.05,
        "cadence_bpm": 121,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_004": {
        "title": "Carve deep core micro-set 4",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 9.4,
        "cadence_bpm": 122,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_005": {
        "title": "Trace scapular micro-set 5",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 9.75,
        "cadence_bpm": 123,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_006": {
        "title": "Weave hip hinge micro-set 6",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 10.1,
        "cadence_bpm": 124,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_007": {
        "title": "Press posterior micro-set 7",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 10.45,
        "cadence_bpm": 125,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_008": {
        "title": "Pulse anterior micro-set 8",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 10.8,
        "cadence_bpm": 126,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_009": {
        "title": "Drive lateral micro-set 9",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 11.15,
        "cadence_bpm": 127,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_010": {
        "title": "Anchor oblique micro-set 10",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 11.5,
        "cadence_bpm": 128,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_011": {
        "title": "Lift deep core micro-set 11",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 11.85,
        "cadence_bpm": 129,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_012": {
        "title": "Carve scapular micro-set 12",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 12.2,
        "cadence_bpm": 130,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_013": {
        "title": "Trace hip hinge micro-set 13",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 12.55,
        "cadence_bpm": 131,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_014": {
        "title": "Weave posterior micro-set 14",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 12.9,
        "cadence_bpm": 132,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_015": {
        "title": "Press anterior micro-set 15",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 13.25,
        "cadence_bpm": 133,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_016": {
        "title": "Pulse lateral micro-set 16",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 13.6,
        "cadence_bpm": 134,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_017": {
        "title": "Drive oblique micro-set 17",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 8.0,
        "cadence_bpm": 135,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_018": {
        "title": "Anchor deep core micro-set 18",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 8.35,
        "cadence_bpm": 136,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_019": {
        "title": "Lift scapular micro-set 19",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 8.7,
        "cadence_bpm": 137,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_020": {
        "title": "Carve hip hinge micro-set 20",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 9.05,
        "cadence_bpm": 138,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_021": {
        "title": "Trace posterior micro-set 21",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 9.4,
        "cadence_bpm": 139,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_022": {
        "title": "Weave anterior micro-set 22",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 9.75,
        "cadence_bpm": 140,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_023": {
        "title": "Press lateral micro-set 23",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 10.1,
        "cadence_bpm": 141,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_024": {
        "title": "Pulse oblique micro-set 24",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 10.45,
        "cadence_bpm": 142,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_025": {
        "title": "Drive deep core micro-set 25",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 10.8,
        "cadence_bpm": 143,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_026": {
        "title": "Anchor scapular micro-set 26",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 11.15,
        "cadence_bpm": 144,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_027": {
        "title": "Lift hip hinge micro-set 27",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 11.5,
        "cadence_bpm": 145,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_028": {
        "title": "Carve posterior micro-set 28",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 11.85,
        "cadence_bpm": 146,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_029": {
        "title": "Trace anterior micro-set 29",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 12.2,
        "cadence_bpm": 147,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_030": {
        "title": "Weave lateral micro-set 30",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 12.55,
        "cadence_bpm": 148,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_031": {
        "title": "Press oblique micro-set 31",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 12.9,
        "cadence_bpm": 149,
        "tags": ("mobility", "strength", "conditioning"),
    },
