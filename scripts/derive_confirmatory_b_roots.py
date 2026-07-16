#!/usr/bin/env python3
"""Derive the fresh, pre-registered root seeds for confirmatory experiment B.

Experiment B is a higher-power, pre-registered replication of the A2 1%
non-inferiority test (CARR vs dense refresh). Its scientific validity requires
root seeds that were NEVER used in any effect analysis. We reuse the exact,
audited A2 derivation FORMULA but change only the domain string, which yields a
deterministic, reproducible, and disjoint root set.

Formula (identical to A1/A2):
    s_i = 100000 + (int(SHA256("<source>|<domain>|<i>")[0:16], 16) mod 900000)

Self-check: the script first reproduces A2's exact ten roots to prove the
formula is byte-identical, then derives B's roots and asserts zero overlap with
the A1 and A2 root sets and zero internal duplicates.
"""

from __future__ import annotations

import hashlib

# Fixed provenance anchor, identical to A1/A2 (the A1 effect-blind failure
# report SHA-256). Using the same source keeps B's derivation tied to the same
# audited anchor; only the domain differs.
SOURCE = "6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48"

A1_DOMAIN = "dai-same-call-confirmatory-a1"  # placeholder; A1 uses its own domain
A2_DOMAIN = "dai-same-call-confirmatory-a2-pid-reuse-correction"
B_DOMAIN = "dai-same-call-confirmatory-b-power-extension"

A1_ROOTS = [767369, 695428, 323681, 904171, 446020, 434435, 488565, 514527, 544573, 838809]
A2_ROOTS = [691817, 376110, 263001, 293231, 296805, 274330, 997942, 319782, 807287, 326454]

N_B_ROOTS = 40


def derive(source: str, domain: str, i: int) -> int:
    h = hashlib.sha256(f"{source}|{domain}|{i}".encode("utf-8")).hexdigest()
    return 100000 + (int(h[0:16], 16) % 900000)


def main() -> None:
    # 1) Self-check: reproduce A2's exact ten roots.
    a2_check = [derive(SOURCE, A2_DOMAIN, i) for i in range(10)]
    assert a2_check == A2_ROOTS, f"formula self-check FAILED: {a2_check} != {A2_ROOTS}"
    print("formula self-check PASS: reproduced A2 roots exactly")
    print(f"  A2 domain = {A2_DOMAIN}")
    print(f"  A2 roots  = {A2_ROOTS}")
    print()

    # 2) Derive B roots at fixed indices i = 0..N-1.
    forbidden = set(A1_ROOTS) | set(A2_ROOTS)
    b_roots: list[int] = []
    per_index = []
    for i in range(N_B_ROOTS):
        s = derive(SOURCE, B_DOMAIN, i)
        per_index.append((i, s))
        b_roots.append(s)

    # 3) Integrity assertions.
    dups = len(b_roots) != len(set(b_roots))
    overlap = sorted(set(b_roots) & forbidden)
    assert not dups, f"B roots contain internal duplicates: {b_roots}"
    assert not overlap, f"B roots overlap A1/A2 roots: {overlap}"

    print(f"B derivation PASS: {N_B_ROOTS} fresh roots, no internal dup, no A1/A2 overlap")
    print(f"  B domain = {B_DOMAIN}")
    print(f"  source   = {SOURCE}")
    print()
    print("B_ROOTS = [")
    for start in range(0, N_B_ROOTS, 10):
        chunk = b_roots[start:start + 10]
        print("    " + ", ".join(str(x) for x in chunk) + ",")
    print("]")
    print()
    print(f"min={min(b_roots)} max={max(b_roots)} count={len(b_roots)} unique={len(set(b_roots))}")


if __name__ == "__main__":
    main()
