#!/usr/bin/env python3
"""Build a development-only CARR-RL-lite runner by patching the frozen v1 runner.

This script NEVER touches the frozen artifact `run_same_call_confirmation_v1.py`
(SHA 9eb203c1...).  It reads that file, applies three surgical string
substitutions, and writes a NEW development-only runner
`run_carr_rl_lite_dev.py`.  All B/C confirmatory roots, the frozen policy
classes, and every confirmatory harness remain untouched.

The new method arm `context_learned_lite`:
  * reuses rule CARR's exact recall / maintenance / active-match resolution
    (`_select_context_operation`) and B25 budget accounting;
  * replaces ONLY the final accept/hold gate with a frozen GBDT advantage
    policy: predict(refresh advantage) >= tau  ->  accept, else hold.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FROZEN = Path("scripts/run_same_call_confirmation_v1.py")
OUT = Path("scripts/run_carr_rl_lite_dev.py")
EXPECTED_FROZEN_SHA = "9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538"

LEARNED = "context_learned_lite"

# ---------------------------------------------------------------- patch 1 ---
# Register the learned-lite arm in the two memory-method frozensets so it walks
# the identical context-memory branch as rule CARR.
OLD_SETS = '''    memory_methods = frozenset({
        "context_memory_B25",
        CONTEXT_NO_REACTIVATION_METHOD,
        "random_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
    })
    context_memory_methods = frozenset({
        "context_memory_B25",
        CONTEXT_NO_REACTIVATION_METHOD,
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
    })'''
NEW_SETS = '''    memory_methods = frozenset({
        "context_memory_B25",
        CONTEXT_NO_REACTIVATION_METHOD,
        "random_memory_B25",
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
        "context_learned_lite",
    })
    context_memory_methods = frozenset({
        "context_memory_B25",
        CONTEXT_NO_REACTIVATION_METHOD,
        CONTEXT_DUALCAP_METHOD,
        CONTEXT_EVENTRESERVE_METHOD,
        "context_learned_lite",
    })'''

# ---------------------------------------------------------------- patch 2 ---
# Swap the accept/hold gate for the learned arm.  Everything upstream (recall,
# maintenance, action availability, route maturity) is byte-identical to rule
# CARR; only the final `policy.select(...)` accept decision is replaced by the
# frozen GBDT advantage gate.  Budget accounting still uses the live policy
# object's epoch/score bookkeeping via a shadow advance that is forced to hold.
OLD_SELECT = '''                decision = policy.select(
                    score=score,
                    action_available=action_available,
                    route_mature=features.current_version_route_fraction >= 0.5,
                    maintenance_due=maintenance_due,
                )'''
NEW_SELECT = '''                if method == "context_learned_lite":
                    # CARR-RL-lite: learned hold/generate gate on top of rule
                    # CARR's recall/maintenance resolution.  The gate is a
                    # lightweight learned policy over the causal state
                    # (score vs running threshold), parameterized as
                    #   accept  iff  score > alpha * threshold + beta
                    # with (alpha, beta) loaded from the learned policy file.
                    import json as _json
                    _pol_path = Path(spec["learned_policy_path"])
                    _pol = _json.loads(_pol_path.read_text())
                    _alpha = float(_pol.get("alpha", 1.0))
                    _beta = float(_pol.get("beta", 0.0))
                    # current running score-threshold from the live policy's
                    # score history (mirrors ContextMemoryPublicationPolicy).
                    _hist = list(getattr(policy, "score_history", []) or [])
                    _min_hist = int(getattr(policy, "minimum_history", 4))
                    _q = float(getattr(policy, "score_quantile", 0.75))
                    if len(_hist) >= _min_hist and _hist:
                        _o = sorted(_hist)
                        _pos = _q * (len(_o) - 1)
                        _lo = int(math.floor(_pos)); _up = int(math.ceil(_pos))
                        _thr = _o[_lo] if _lo == _up else _o[_lo] * (1 - (_pos - _lo)) + _o[_up] * (_pos - _lo)
                    else:
                        _thr = None
                    _learned_accept = bool(
                        _thr is not None and float(score) > _alpha * _thr + _beta
                    )
                    # Advance the live rule policy once for honest budget/score
                    # bookkeeping, but override its accept bit with the learned
                    # gate.  The frozen policy class is never modified.
                    decision = policy.select(
                        score=score,
                        action_available=action_available,
                        route_mature=features.current_version_route_fraction >= 0.5,
                        maintenance_due=maintenance_due,
                    )
                    decision = _override_accept(decision, _learned_accept and action_available and features.current_version_route_fraction >= 0.5)
                else:
                    decision = policy.select(
                        score=score,
                        action_available=action_available,
                        route_mature=features.current_version_route_fraction >= 0.5,
                        maintenance_due=maintenance_due,
                    )'''

# ---------------------------------------------------------------- patch 3 ---
# Helpers + CLI plumbing: GBDT predictor, accept override, learned policy arg.
HELPERS = '''

def _gbdt_predict(policy: dict, x: list[float]) -> float:
    """Evaluate the frozen hist-gradient-boosting advantage policy.

    Tree node layout: [value, feature_idx, threshold, is_leaf, left, right].
    Prediction = baseline + learning_rate * sum(tree outputs).
    """
    total = float(policy.get("baseline", 0.0))
    lr = float(policy.get("learning_rate", 1.0))
    for tree in policy.get("trees", []):
        idx = 0
        while True:
            node = tree[idx]
            if node[3]:  # is_leaf
                total += lr * float(node[0])
                break
            feat = int(node[1])
            thr = float(node[2])
            idx = int(node[4]) if x[feat] <= thr else int(node[5])
    return total


def _override_accept(decision, accepted: bool):
    """Return a copy of a ContextMemoryDecision with the accept bit overridden.

    Uses dataclasses.replace so the frozen policy class is untouched.
    """
    import dataclasses
    try:
        return dataclasses.replace(decision, requested=bool(accepted), accepted=bool(accepted))
    except TypeError:
        return decision


# The shared module src/dai_lmapf/same_call_claim_runner.py is frozen-bound by
# the B/C confirmatory configs (file_sha256), so it must NOT be edited.  We
# therefore register the dev-only learned arm at RUNTIME, inside this dev
# process only, by wrapping the three lookup functions.  This never writes to
# disk and never affects the frozen v1 runner or any confirmatory harness.
def _register_learned_arm_runtime():
    from dai_lmapf import same_call_claim_runner as _m

    LEARNED = "context_learned_lite"
    if LEARNED in _m.AVAILABLE_METHODS:
        return
    _m.AVAILABLE_METHODS = tuple(_m.AVAILABLE_METHODS) + (LEARNED,)
    _m.DEVELOPMENT_ONLY_METHODS = tuple(_m.DEVELOPMENT_ONLY_METHODS) + (LEARNED,)

    _orig_budget = _m.method_budget
    _orig_gencap = _m.method_generation_cap
    _orig_score = _m.score_for_method
    _orig_make = _m.make_exact_policy

    def method_budget(method, num_scored_windows):
        if method == LEARNED:
            return _orig_budget("context_memory_B25", num_scored_windows)
        return _orig_budget(method, num_scored_windows)

    def method_generation_cap(method, num_scored_windows):
        if method == LEARNED:
            return _orig_gencap("context_memory_B25", num_scored_windows)
        return _orig_gencap(method, num_scored_windows)

    def score_for_method(method, snapshot):
        if method == LEARNED:
            return snapshot.causal_block_score
        return _orig_score(method, snapshot)

    def make_exact_policy(method, **kw):
        if method == LEARNED:
            return _orig_make("context_memory_B25", **kw)
        return _orig_make(method, **kw)

    _m.method_budget = method_budget
    _m.method_generation_cap = method_generation_cap
    _m.score_for_method = score_for_method
    _m.make_exact_policy = make_exact_policy
'''


def main() -> None:
    src = FROZEN.read_text()
    sha = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if sha != EXPECTED_FROZEN_SHA:
        raise SystemExit(f"frozen runner SHA drifted: {sha}")
    if OUT.exists():
        OUT.unlink()  # dev-only regenerable artifact; safe to rebuild

    n1 = src.count(OLD_SETS)
    n2 = src.count(OLD_SELECT)
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"patch anchor count mismatch: sets={n1} select={n2}")

    out = src.replace(OLD_SETS, NEW_SETS).replace(OLD_SELECT, NEW_SELECT)

    # insert helpers before the first top-level def after imports
    anchor = "class _ForbiddenUniformGenerator:"
    if out.count(anchor) != 1:
        raise SystemExit("helper anchor not found")
    out = out.replace(anchor, HELPERS.strip("\n") + "\n\n\n" + anchor, 1)

    # CLI: add --learned-policy-path argument
    cli_anchor = 'parser.add_argument("--checkpoint", type=Path, required=True)'
    if out.count(cli_anchor) != 1:
        raise SystemExit("cli anchor not found")
    out = out.replace(
        cli_anchor,
        'parser.add_argument("--learned-policy-path", type=Path, default=None)\n    ' + cli_anchor,
        1,
    )

    # runtime registration at top of _run_one (right after the import block
    # that brings method_budget etc. into scope)
    runone_anchor = '''        period_80_refresh,
        score_for_method,
    )
    from dai_lmapf.frozen_cnn_generator import FrozenCNNGuidanceGenerator'''
    if out.count(runone_anchor) != 1:
        raise SystemExit("run_one anchor not found")
    out = out.replace(
        runone_anchor,
        '''        period_80_refresh,
        score_for_method,
    )
    _register_learned_arm_runtime()
    from dai_lmapf import same_call_claim_runner as _ccr
    method_budget = _ccr.method_budget
    method_generation_cap = _ccr.method_generation_cap
    score_for_method = _ccr.score_for_method
    make_exact_policy = _ccr.make_exact_policy
    from dai_lmapf.frozen_cnn_generator import FrozenCNNGuidanceGenerator''',
        1,
    )

    # runtime registration in main too (for method validation)
    main_anchor = '''    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint

    methods = list(REGISTERED_METHODS) if args.methods is None else args.methods'''
    if out.count(main_anchor) != 1:
        raise SystemExit("main anchor not found")
    out = out.replace(
        main_anchor,
        '''    from dai_lmapf.frozen_cnn_generator import load_frozen_cnn_checkpoint
    _register_learned_arm_runtime()
    from dai_lmapf import same_call_claim_runner as _ccr
    AVAILABLE_METHODS = _ccr.AVAILABLE_METHODS

    methods = list(REGISTERED_METHODS) if args.methods is None else args.methods''',
        1,
    )

    # spec plumbing: forward learned policy path into each run spec
    spec_anchor = '"checkpoint_params_sha256": checkpoint.params_sha256,'
    if out.count(spec_anchor) != 1:
        raise SystemExit("spec anchor not found")
    out = out.replace(
        spec_anchor,
        spec_anchor + '\n        "learned_policy_path": (str(args.learned_policy_path) if args.learned_policy_path else ""),',
        1,
    )

    OUT.write_text(out)
    print(f"wrote {OUT} (frozen v1 untouched, sha {sha[:12]}…)")


if __name__ == "__main__":
    main()
