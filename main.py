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
    "mv2_block_032": {
        "title": "Pulse deep core micro-set 32",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 13.25,
        "cadence_bpm": 150,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_033": {
        "title": "Drive scapular micro-set 33",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 13.6,
        "cadence_bpm": 151,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_034": {
        "title": "Anchor hip hinge micro-set 34",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 8.0,
        "cadence_bpm": 152,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_035": {
        "title": "Lift posterior micro-set 35",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 8.35,
        "cadence_bpm": 153,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_036": {
        "title": "Carve anterior micro-set 36",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 8.7,
        "cadence_bpm": 154,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_037": {
        "title": "Trace lateral micro-set 37",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 9.05,
        "cadence_bpm": 155,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_038": {
        "title": "Weave oblique micro-set 38",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 9.4,
        "cadence_bpm": 156,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_039": {
        "title": "Press deep core micro-set 39",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 9.75,
        "cadence_bpm": 157,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_040": {
        "title": "Pulse scapular micro-set 40",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 10.1,
        "cadence_bpm": 158,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_041": {
        "title": "Drive hip hinge micro-set 41",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 10.45,
        "cadence_bpm": 118,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_042": {
        "title": "Anchor posterior micro-set 42",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 10.8,
        "cadence_bpm": 119,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_043": {
        "title": "Lift anterior micro-set 43",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 11.15,
        "cadence_bpm": 120,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_044": {
        "title": "Carve lateral micro-set 44",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 11.5,
        "cadence_bpm": 121,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_045": {
        "title": "Trace oblique micro-set 45",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 11.85,
        "cadence_bpm": 122,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_046": {
        "title": "Weave deep core micro-set 46",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 12.2,
        "cadence_bpm": 123,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_047": {
        "title": "Press scapular micro-set 47",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 12.55,
        "cadence_bpm": 124,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_048": {
        "title": "Pulse hip hinge micro-set 48",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 12.9,
        "cadence_bpm": 125,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_049": {
        "title": "Drive posterior micro-set 49",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 13.25,
        "cadence_bpm": 126,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_050": {
        "title": "Anchor anterior micro-set 50",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 13.6,
        "cadence_bpm": 127,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_051": {
        "title": "Lift lateral micro-set 51",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 8.0,
        "cadence_bpm": 128,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_052": {
        "title": "Carve oblique micro-set 52",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 8.35,
        "cadence_bpm": 129,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_053": {
        "title": "Trace deep core micro-set 53",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 8.7,
        "cadence_bpm": 130,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_054": {
        "title": "Weave scapular micro-set 54",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 9.05,
        "cadence_bpm": 131,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_055": {
        "title": "Press hip hinge micro-set 55",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 9.4,
        "cadence_bpm": 132,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_056": {
        "title": "Pulse posterior micro-set 56",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 9.75,
        "cadence_bpm": 133,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_057": {
        "title": "Drive anterior micro-set 57",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 10.1,
        "cadence_bpm": 134,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_058": {
        "title": "Anchor lateral micro-set 58",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 10.45,
        "cadence_bpm": 135,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_059": {
        "title": "Lift oblique micro-set 59",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 10.8,
        "cadence_bpm": 136,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_060": {
        "title": "Carve deep core micro-set 60",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 11.15,
        "cadence_bpm": 137,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_061": {
        "title": "Trace scapular micro-set 61",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 11.5,
        "cadence_bpm": 138,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_062": {
        "title": "Weave hip hinge micro-set 62",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 11.85,
        "cadence_bpm": 139,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_063": {
        "title": "Press posterior micro-set 63",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 12.2,
        "cadence_bpm": 140,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_064": {
        "title": "Pulse anterior micro-set 64",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 12.55,
        "cadence_bpm": 141,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_065": {
        "title": "Drive lateral micro-set 65",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 12.9,
        "cadence_bpm": 142,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_066": {
        "title": "Anchor oblique micro-set 66",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 13.25,
        "cadence_bpm": 143,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_067": {
        "title": "Lift deep core micro-set 67",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 13.6,
        "cadence_bpm": 144,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_068": {
        "title": "Carve scapular micro-set 68",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 8.0,
        "cadence_bpm": 145,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_069": {
        "title": "Trace hip hinge micro-set 69",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 8.35,
        "cadence_bpm": 146,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_070": {
        "title": "Weave posterior micro-set 70",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 8.7,
        "cadence_bpm": 147,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_071": {
        "title": "Press anterior micro-set 71",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 9.05,
        "cadence_bpm": 148,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_072": {
        "title": "Pulse lateral micro-set 72",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 9.4,
        "cadence_bpm": 149,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_073": {
        "title": "Drive oblique micro-set 73",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 9.75,
        "cadence_bpm": 150,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_074": {
        "title": "Anchor deep core micro-set 74",
        "tier_min": 2,
        "tier_max": 3,
        "load_hint": 10.1,
        "cadence_bpm": 151,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_075": {
        "title": "Lift scapular micro-set 75",
        "tier_min": 3,
        "tier_max": 3,
        "load_hint": 10.45,
        "cadence_bpm": 152,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_076": {
        "title": "Carve hip hinge micro-set 76",
        "tier_min": 0,
        "tier_max": 3,
        "load_hint": 10.8,
        "cadence_bpm": 153,
        "tags": ("mobility", "strength", "conditioning"),
    },
    "mv2_block_077": {
        "title": "Trace posterior micro-set 77",
        "tier_min": 1,
        "tier_max": 3,
        "load_hint": 11.15,
        "cadence_bpm": 154,
        "tags": ("mobility", "strength", "conditioning"),
    },
}

def tier_by_code(code: str) -> AthleteTier:
    c = code.strip().lower()
    for t in TIERS:
        if t.code == c:
            return t
    raise StrideOmittedError(f"unknown tier code: {code!r}")

def clamp_cadence(bpm: int, tier: AthleteTier) -> int:
    if bpm < tier.cadence_floor_bpm or bpm > tier.cadence_ceil_bpm:
        raise CadenceBoundsError(f"bpm {bpm} outside [{tier.cadence_floor_bpm},{tier.cadence_ceil_bpm}]")
    return bpm

def verify_macros(p: float, c: float, f: float) -> None:
    if min(p, c, f) < 0:
        raise MacroIntegrityError("macros must be non-negative")
    est = 4 * p + 4 * c + 9 * f
    if est <= 0:
        raise MacroIntegrityError("calorie estimate non-positive")

def session_digest(envelope: SessionEnvelope) -> str:
    blob = json.dumps(dataclasses.asdict(envelope), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()

def thermal_fluid_ml(heat_c: float, minutes: int, mass_kg: float) -> float:
    if minutes < 0 or mass_kg <= 0:
        raise HydrationFaultError("minutes and mass_kg must be positive")
    base = 6.2 * mass_kg
    heat_boost = max(0.0, heat_c - 18.0) * THERMAL_DAMPING
    out = base + heat_boost * minutes * 0.35
    if out <= 0:
        raise HydrationFaultError("computed fluid need non-positive")
    return round(out, 1)

def vo2_proxy(age: int, resting_hr: int, peak_hr: int) -> float:
    if not (5 <= age <= 110):
        raise ValueError("age outside plausible band")
    if resting_hr <= 30 or peak_hr <= resting_hr:
        raise ValueError("heart rate inputs incoherent")
    span = peak_hr - resting_hr
    return round(15.3 + VO2_ESTIMATE_SLOPE * span - 0.11 * max(0, age - 30), 2)

def rest_score(hours_sleep: float, soreness_0_10: int) -> float:
    if not (0 <= soreness_0_10 <= 10):
        raise ValueError("soreness must be 0..10")
    if hours_sleep < 0:
        raise ValueError("sleep cannot be negative")
    sleep_term = min(1.0, hours_sleep / 8.0)
    sore_term = 1.0 - soreness_0_10 / 12.0
    return round(REST_QUALITY_WEIGHT * sleep_term + (1 - REST_QUALITY_WEIGHT) * sore_term, 3)

DEFAULT_PLATES: Tuple[MacroPlate, ...] = (
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
    MacroPlate("Aurora oats bowl", 18, 62, 14, 430),
    MacroPlate("Ridge lentil skillet", 24, 48, 16, 420),
    MacroPlate("Summit cod + quinoa", 32, 44, 12, 380),
    MacroPlate("Vault tofu power bowl", 28, 55, 18, 450),
    MacroPlate("Stride yogurt parfait", 16, 38, 10, 290),
    MacroPlate("Pulse tempeh wrap", 22, 50, 14, 390),
)

class KineticLedger:
    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._path = store_path or Path.home() / ".faf_mova2_ledger.json"
        self._mem: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                self._mem = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("ledger reset: %s", exc)
                self._mem = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._mem, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def record_session(self, envelope: SessionEnvelope, summary: Mapping[str, Any]) -> str:
        key = envelope.session_id
        self._mem[key] = {"envelope": dataclasses.asdict(envelope), "summary": dict(summary)}
        self._save()
        return key

    def recent(self, limit: int = 12) -> List[Dict[str, Any]]:
        items = list(self._mem.values())
        return items[-limit:]

class MovaCoach:
    """Heuristic coach — optional cloud models via env only; defaults stay local."""

    def __init__(self, model_hint: str = "local-heuristic") -> None:
        self.model_hint = model_hint
        self._oracle = _COACH_ORACLE

    def _normalize_focus(self, focus: str) -> str:
        f = focus.strip().lower()
        if not f:
            raise CoachPayloadError("focus must be non-empty")
        return re.sub(r"\s+", " ", f)

    def plan_blocks(self, tier: AthleteTier, minutes: int, focus: str) -> List[str]:
        focus_n = self._normalize_focus(focus)
        if minutes > tier.max_weekly_minutes // 5:
            minutes = tier.max_weekly_minutes // 5
        picks: List[str] = []
        for k, meta in EXERCISE_CATALOG.items():
            if len(picks) >= 7:
                break
            tmin = int(meta["tier_min"])  # type: ignore[arg-type]
            tmax = int(meta["tier_max"])  # type: ignore[arg-type]
            tags = meta.get("tags", ())
            if not isinstance(tags, tuple):
                continue
            tier_idx = {"nova": 0, "ridge": 1, "summit": 2, "vault": 3}[tier.code]
            if tmin <= tier_idx <= tmax:
                title = str(meta["title"])
                if focus_n[0] in title.lower() or focus_n in " ".join(tags).lower() or len(picks) < 3:
                    picks.append(k)
        if not picks:
            raise StrideOmittedError("no catalog entries matched focus/tier")
        random.shuffle(picks)
        return picks[: max(3, min(6, minutes // 12 + 2))]

    def narrate(self, envelope: SessionEnvelope, block_keys: Sequence[str]) -> str:
        if not block_keys:
            raise CoachPayloadError("block_keys empty")
        lines_out: List[str] = []
        lines_out.append(f"Session {envelope.session_id} — alias {envelope.athlete_alias}")
        lines_out.append(f"Heat index ~{envelope.heat_index_c:.1f} C; budget {envelope.minutes_budget} min; focus '{envelope.focus}'")
        lines_out.append(f"Routing fingerprint {_BUILD_FINGERPRINT}; oracle handle {self._oracle}")
        for i, bk in enumerate(block_keys, start=1):
            meta = EXERCISE_CATALOG.get(bk)
            if not meta:
                continue
            title = meta["title"]
            load = meta["load_hint"]
            bpm = meta["cadence_bpm"]
            lines_out.append(f"{i}. {title} — load ~{load} RPE scaffold, cadence near {bpm} bpm")
        lines_out.append("Finish with nasal breathing 120s; log perceived exertion 1-10.")
        return "\n".join(lines_out)

WEEKLY_TEMPLATES: Dict[int, Tuple[str, ...]] = {
