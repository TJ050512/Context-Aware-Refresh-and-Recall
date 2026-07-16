# DAI 2026 Research Track — Final Registration Fields

> Updated against the completed A2 confirmation matrix on 14 July 2026.
> This file supersedes every earlier registration draft. Do not reuse the old
> plan-only abstract, baseline list, map list, metric list, or timing claims.

## Title

When Should Global Guidance Be Refreshed? A Paired Pareto Study in Lifelong Multi-Agent Path Finding

## Authors

1. Xiaoxiao Ma
2. Xiankun Jiang

Keep this order only if both authors have approved the author list and order.

## Keywords

lifelong multi-agent path finding, multi-robot coordination, distributed multi-agent systems, adaptive global guidance, resource-aware planning, event-triggered refresh, non-stationary workloads, Pareto analysis

## TL;DR

Across 960 audited runs on a frozen LMAPF backbone, context-aware refresh and recall forms a non-dominated sample-mean throughput–generator-call operating point and uses 78.97% fewer generator calls than dense refresh, although 1% throughput non-inferiority is not established.

## Abstract

Lifelong multi-agent path finding (LMAPF) requires robot fleets to serve an ongoing stream of goals while avoiding congestion. Learned global guidance can improve traffic flow, but existing online methods commonly refresh guidance at fixed intervals. Frequent refresh consumes generator calls even when demand is stable, whereas infrequent refresh may leave guidance stale after workload shifts. We formulate refresh timing as a budgeted control problem and introduce Context-Aware Refresh and Recall (CARR), which causally chooses to retain active guidance, generate a new graph, or reactivate a previously generated one using demand change, context similarity, guidance age, and route-adoption signals. CARR wraps a frozen generator and planner without retraining either. We evaluate eight refresh policies on non-stationary warehouse workloads using paired, policy-independent task streams and an audit-complete protocol. CARR forms a non-dominated sample-mean throughput–generator-call operating point, substantially reducing calls relative to dense periodic refresh while outperforming several low-call baselines. Dense refresh has a slightly higher observed mean throughput, and pre-specified 1% non-inferiority is not established. Our results identify guidance timing as an independent systems-design dimension and provide a reproducible basis for choosing refresh policies according to resource constraints.

## PDF

Leave empty until the anonymous full paper is ready.

## Primary Topic Area

Embodied Multi-Agent Systems

## Secondary Topic Areas

- Agent Engineering & Infrastructure
- Multi-Agent Cooperation & Human-Agent Interaction

Do not select `Foundations of Agent Learning`: the evaluated refresh
controller is not a newly trained learning algorithm.

## Supplementary Material

Leave empty at registration. Upload only an anonymized artifact at the
full-paper stage.

## AI Use Disclosure

OpenAI Codex was used substantively for literature discovery, research-design brainstorming, code scaffolding and debugging, experimental-protocol development, experiment orchestration, deterministic data-analysis scripting, and drafting/editing text. The authors made the scientific decisions and retain full responsibility for the accuracy, originality, and integrity of the work. Numerical claims are traceable to frozen experiment artifacts, and the authors will verify all citations, code, analyses, and manuscript claims before submission. No AI system is listed as an author.

## Additional Information

Leave blank.

## Unchanged system fields

- License: CC BY 4.0
- Readers: DAI 2026 Research Track and authors
- Signatures: the submitting author

## Mandatory claim boundaries

- The protocol and analysis were internally pre-specified and frozen before
  A2 execution; they were not publicly preregistered.
- The 1% non-inferiority criterion failed.
- Historical reactivation did not show a throughput benefit.
- The Pareto frontier is based on sample means among the eight evaluated
  same-backbone controllers.
- Generator calls are a registered logical resource unit, not wall-clock,
  energy, GPU-time, or monetary cost.
- The evidence does not establish global LMAPF SOTA.
