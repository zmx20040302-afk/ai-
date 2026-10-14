# -*- coding: utf-8 -*-
"""Structural content of the frozen closed-loop pre-registration, as data (no prose).

WHY THIS FILE, AND WHY IT IS SAFE TO TRUST
The pre-registration document itself is **not distributed** with this package: it is an internal
artifact that carries internal paths and a model filename, and its prose exists for human readers
rather than for replay. What the replay actually needs is structure: the candidate pool, the shared
DOE, the per-arm seed lists and the call budget. Those are reproduced here as data.

This file was **generated** from the frozen document by `emit_t7_frozen_protocol.py`, never typed by
hand. The generator asserts that rebuilding the pool from these values reproduces the pool sha256 that
`t7_scheduling.py` checks at run time, and that the pool size matches; if either failed it refused to
write this file. So the numbers here are not a transcription claim - they are checked against the
frozen pre-registration's own digest.

Frozen pre-registration identity:
    file   : PREREG_T7.json (not distributed)
    sha256 : 78f2ee62a0a3919fdac1bd371fa116c7e70ebb04e0e81663c6353959bf434a0c
"""
from __future__ import annotations

SOURCE_SHA256 = "78f2ee62a0a3919fdac1bd371fa116c7e70ebb04e0e81663c6353959bf434a0c"
KIND = "n3_closed_loop_dse_preregistration"
STATUS = "FROZEN_BEFORE_THE_MULTISEED_EXTENSION_RUN"

# 36 x-values x N pool pairs = 1080 candidate designs
X_VALUES = [0.45, 0.46, 0.47, 0.48, 0.49, 0.5, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.6, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67, 0.68, 0.69, 0.7, 0.71, 0.72, 0.73, 0.74, 0.75, 0.76, 0.77, 0.78, 0.79, 0.8]
N1N2_PAIRS = [[1, 5], [2, 5], [3, 5], [4, 5], [1, 6], [2, 6], [3, 6], [4, 6], [5, 6], [1, 7], [2, 7], [3, 7], [4, 7], [5, 7], [6, 7], [1, 8], [2, 8], [3, 8], [4, 8], [5, 8], [6, 8], [7, 8], [1, 9], [2, 9], [3, 9], [4, 9], [5, 9], [6, 9], [7, 9], [8, 9]]
POOL_SIZE = 1080
POOL_SHA256 = "db3119ddd50c4f7f7b6d9a3e76fd6fc2d38d34487fccb3ee911e95c9a6c09b4c"

SHARED_DOE = [[0.5, 1, 5], [0.55, 2, 6], [0.6, 4, 9], [0.65, 3, 7], [0.7, 5, 9]]
ARM_SEEDS = {'A1_random': [0, 1, 2, 3, 4], 'A2_greedy': [0, 1, 2, 3, 4], 'A3_gp_ei': [0, 1, 2, 3, 4], 'A4_gp_ei_gated': [0, 1, 2, 3, 4]}
BUDGET = {'doe_calls': 5, 'arm_calls': 100, 'total_calls': 105, 'predicted_wall_min_at_60s_per_call': 105.0}
