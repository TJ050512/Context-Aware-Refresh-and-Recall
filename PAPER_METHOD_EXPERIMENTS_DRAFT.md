# Method and Experiments (Claim-Bearing Draft)

> **Evidence status, 14 July 2026.** Sections 3--4 describe the frozen
> claim-bearing implementation and validation-v2 protocol. Section 5.1 reports
> development evidence only; Section 5.2 reports a negative development
> ablation; Section 5.3 reports the completed fresh validation-v2 analysis.
> Validation-v2 returned `NO_GO_RETURN_TO_DEVELOPMENT`, and the locked test
> remains sealed. Nothing in this draft establishes global lifelong-MAPF SOTA.
> The treatment freeze is identified by
> `configs/validation_v2_treatment_freeze_manifest.json`; the development source
> artifact is
> `results/official_gate0/claim_full_dev10_h2000_v7.json` (SHA-256
> `d971c23983bb9e2b1bc517cea0db19fd5da5bc97a16b6a2aa3a777c06b7ff9f7`).

## 3 Method

### 3.1 Budgeted guidance control for lifelong MAPF

Let $G=(V,E)$ be a directed grid graph and let $n$ agents repeatedly execute
released pickup-and-delivery tasks. At each simulator timestep an agent waits or
traverses an adjacent edge; vertex collisions and opposing edge swaps are
forbidden. The GPIBT planner uses a directed-edge guidance tensor to bias route
construction. A frozen convolutional generator $F_\theta$ maps the causal
traffic observation at decision $k$ to a raw tensor

\[
    w_k=F_\theta(o_{\le t_k})\in\mathbb{R}^{4\times H_m\times W_m}.
\]

The OnlineGGO environment masks invalid edges and normalizes this tensor before
the C++ planner consumes it. We distinguish the immutable raw tensor $w_k$ from
the applied tensor $\bar w_k$ and hash both.

An episode has a 200-step warm-up and a scored horizon $H=2000$. Decisions are
made every $D=20$ simulator steps, so there are $N=H/D=100$ scored windows. All
non-uniform methods make one mandatory generator call after warm-up and before
the first scored window. This bootstrap installs guidance version 1 but is not
charged to the post-bootstrap budget. Decision zero therefore cannot spend a
budget token, leaving $K=N-1=99$ eligible decisions. The primary budget is

\[
    B_{25}=\left\lceil 0.25K\right\rceil=25.
\]

For a controller $\pi$, let $C_\pi(H)$ be the number of nonzero-service tasks
completed in the scored horizon. The main optimization problem is

\[
    \max_\pi\;\mathbb{E}[C_\pi(H)/H]
    \quad\text{s.t.}\quad S_\pi\le B_{25},
    \qquad G_\pi\le B_{25},
\]

where $S_\pi$ is the number of effective post-bootstrap guidance switches and
$G_\pi$ is the number of post-bootstrap fresh generator calls. For ordinary
two-action controllers every switch is a fresh generation, so $S_\pi=G_\pi$.
The three-action memory controller can instead reinstall a historical graph,
giving $G_\pi\le S_\pi$. Controllers designated *exact-B25* must spend exactly
25 post-bootstrap tokens; capped controllers may abstain.

A **hold** does not skip the simulator or the planner. The adapter re-sends a
defensive copy of the cached raw tensor to `env.step`, so task release, motion,
reward, A*, and PIBT continue normally. Re-sending the already normalized tensor
would normalize it twice and is prohibited.

### 3.2 Exogenous absolute-release task tapes

Completion-driven online sampling confounds policy and workload: a faster policy
advances the task RNG sooner and can receive a different future task sequence.
We remove this feedback with a complete task tape constructed before timestep
zero. For agent $i$,

\[
    \mathcal T_i=((g_{i,0},r_{i,0}),\ldots,(g_{i,L_i-1},r_{i,L_i-1})),
\]

where $g_{i,j}$ is a flattened Kiva location and $r_{i,j}$ is an absolute
release timestep. Releases are nondecreasing and enter a per-agent FIFO backlog:
$r=0$ is visible before the first plan, while $r=t>0$ is inserted after the move
ending at $t$ and before the decision at $t$. A busy agent can accumulate queued
tasks. No goal or release time is sampled online, and every method receives the
same starts, releases, goals, and task IDs.

Regular releases are deterministically staggered across agents. Each agent has
release interval 110, yielding nominal aggregate arrival rate $n/110$. Four
guard tasks per agent are released at the final non-scoring boundary; they are a
sentinel against finite-tape exhaustion, not scored arrivals. Task IDs are the
agent-major contiguous offset plus the per-agent tape index. Python records a
canonical SHA-256 manifest and C++ independently records an FNV-1a-64 content
fingerprint. The run is invalid if identities, starts, release projections, or
per-agent assignment/completion prefixes disagree across methods, if the tape is
exhausted, or if the backend performs any online workload RNG draw.

The three workload families differ only in the endpoint distribution used to
generate each task offline:

- **stationary:** one hotspot distribution throughout;
- **abrupt:** four well-separated hotspot distributions, changing at scored
  offsets 500, 1000, and 1500; and
- **recurrent:** $A\!\rightarrow\!B\!\rightarrow\!A\!\rightarrow\!B$ at the
  same offsets.

Adjacent endpoint distributions must have JS divergence at least 0.30 under
$\sigma=0.75$. The latent centers, phase boundaries, future tape suffix, and
distribution-update metadata are audit-only and are forbidden controller inputs.
Thus the protocol evaluates non-stationary, exogenous arrivals with per-agent
queues and a fixed policy-independent workload.

### 3.3 Guidance generations, installations, and route cohorts

Guidance has two identities. A **generation ID** denotes one immutable output of
$F_\theta$ and remains stable if that graph is recalled. An **installation
version** increments whenever a new or historical graph becomes the effective
routing treatment. Every catalog entry stores the generation ID, source, raw
SHA-256, applied SHA-256, and generation context. A requested reactivation whose
generation ID, raw hash, or applied hash is already active is downgraded to a
hold; this prevents a logical “switch” with no physical treatment change.

Publishing guidance is a future-route intervention. It does not retroactively
rebuild every in-flight path. Consequently, routes constructed under multiple
installation versions can coexist after a switch. We instrument every actual
route construction with agent, task, goal, timestep, installation version,
raw/applied hashes, and one of the audited reasons `init_pp`, `task_change`, or
`inherited_goal_route`. A completion enters cohort $\mathcal C_v$ only if its
first actual route build used version $v$. The latest build version of every
active route is retained for maturity features, and later rebuilds remain in the
trace. A completion without a matching assignment and route exposure is an
integrity error, except for the explicitly audited one-step zero-route case,
which is excluded from cohort statistics.

For the active version $v_k$, we use two causal maturity summaries:

\[
 m_k^{\mathrm{route}}
 =\frac{\#\{\text{active agents whose latest route uses }v_k\}}{
         \#\{\text{active agents}\}},
\]

and

\[
 m_k=\max\!\left(m_k^{\mathrm{route}},
 \min\!\left(1,
 \frac{\#\{\text{route builds under }v_k\}}
      {\max(8,\lceil0.25n\rceil)}\right)\right).
\]

These features prevent a controller from repeatedly replacing guidance before
the fleet has substantially adopted it. Cohort service times are descriptive
and causal controller features only after their completions are observed; they
are not interpreted as unadjusted treatment effects.

### 3.4 A release-only causal change score

At every decision we bin goals released during the trace window into a $4\times4$
spatial histogram and add 0.5 pseudocount per bin. Windows without a release are
marked missing rather than converted to a uniform observation. Let $p_k^f$ be
the mean of non-missing histograms in the latest two windows and $p_k^s$ the
mean of up to six non-missing preceding windows. The normalized release-change
score is

\[
    z_k=\frac{\operatorname{JS}(p_k^f,p_k^s)}{\log 2}\in[0,1],
\]

or zero when either side is unavailable. This score uses only tasks whose
release event has already occurred. It does not use active-task composition,
latent phase clocks, or unreleased goals. Both focal controllers compare $z_k$
with the online 75th percentile of its causal score history after four history
observations.

### 3.5 Causal-Block: event-driven timing with exact budget matching

`causal_block_B25` isolates timing quality from budget quantity. The 99 eligible
decisions are partitioned into 25 even-quota buckets, each ending at the
corresponding `exact_even_B25` publication epoch. Exactly one token is spent in
each bucket. A high release-change score may move the bucket's token earlier by
at most two windows when (i) $z_k$ reaches the historical 75th percentile, (ii)
$m_k\ge0.5$, and (iii) at least two windows have elapsed since the preceding
publication. If these conditions never hold, the token is spent at the bucket
end. The policy therefore preserves the exact 25-call budget and cannot defer a
burst of feasibility publications to the end of the episode. Its comparison to
`exact_even_B25` asks a focused question: with the number of generator calls
held fixed, does causal retiming improve throughput?

### 3.6 Context-Memory: hold, reactivate, or generate

`context_memory_B25` treats guidance as a reusable catalog rather than a
disposable stream. Its action is

\[
    a_k\in\{\textsc{hold},\textsc{reactivate}(j),\textsc{generate}\}.
\]

For every fresh generation $j$, we store the $4\times4$ distribution $c_j$ of
currently active goals. At decision $k$, let $c_k$ be the current active-goal
context and let

\[
 d_{k,j}=\operatorname{JS}(c_k,c_j)/\log 2.
\]

Writing $a$ for the active generation and $j^*$ for the nearest non-active
catalog entry, recall is available when

\[
 d_{k,j^*}\le0.05
 \quad\text{and}\quad
 d_{k,a}-d_{k,j^*}\ge0.02.
\]

Otherwise the controller holds if the active context already matches
($d_{k,a}\le0.05$), and proposes a fresh generation if it does not. A maintenance
generation is also proposed after guidance age 25 windows when the release-only
change score is at most 0.20.

A proposed action is executed only if either the event score is exceptional
($z_k\ge0.10$ and strictly above its historical 75th percentile) or maintenance
is due, the current-version active-route fraction is at least 0.5, at least six
windows have elapsed since the last switch, at least three effect windows
remain, and the cap is unspent. The persistence requirement is one window. Both
effective switches and fresh generations are capped at $B_{25}$; there is no
catch-up or forced budget fill. Reactivation invokes no generator call but does
create a new installation version when its applied graph differs from the
active one.

This construction separates two potential benefits: *selectivity* can avoid
harmful publications, while *memory* can reuse a previously suitable treatment
without paying a new generation. Route-maturity gates are essential because a
new installation influences only routes built afterward.

## 4 Experimental Design

### 4.1 Frozen backbone and generator

All methods use the same pinned OnlineGGO/GPIBT backend through the official
`period_on_sim` interface. The validation treatment uses the frozen 10k
convolutional update-model checkpoint (3,084 parameters; 6 input channels, 32
hidden channels, and 4 output channels). Its immutable identities are:

- checkpoint file SHA-256:
  `e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d`;
- float32 parameter SHA-256:
  `6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac`;
- instrumented `period_on_sim` SHA-256:
  `9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5`.

The checkpoint is frozen before fresh validation; training provenance is not a
held-out performance result. Controller comparisons vary only publication
logic, not planner, generator weights, tape, timeout, or simulator binary.

### 4.2 Maps, densities, workloads, and splits

Validation-v2 crosses two Kiva maps, two rounded free-space densities, three
workloads, and ten fresh root seeds:

| Map | Free cells | $\rho$ | Agents | Role |
|---|---:|---:|---:|---|
| `warehouse_small_narrow_kiva` | 1,091 | 0.20 | 218 | Density robustness on the developed topology |
| `warehouse_small_narrow_kiva` | 1,091 | 0.35 | 382 | Density robustness on the developed topology |
| `warehouse_small_kiva` | 1,277 | 0.20 | 255 | Fresh validation topology |
| `warehouse_small_kiva` | 1,277 | 0.35 | 447 | Fresh validation topology |

Agent counts use $\operatorname{round}(\rho|V_{free}|)$, not floor. The full
matrix is $4\times3\times10\times13=1560$ runs in four artifacts. Once any
fresh seed is opened, every artifact must include the complete seed vector,
all workloads, and the complete formal method family; selective cell deletion
and artifact overwrite are forbidden.

Development uses root seeds 17--26. Earlier seeds 101--110 are canonically
`contaminated_pilot_validation`: they helped earlier iteration and cannot be
used as fresh evidence. The fresh validation-v2 vector

`[320019, 241771, 827130, 693142, 741084, 12102, 133633, 876480, 50620, 131545]`

was derived and frozen from the SHA-256 of the completed development artifact
before any member was run. Locked seeds 1001--1030 and the sortation topology
remain sealed. Validation-v2 may choose claim language and whether a candidate
proceeds, but only a once-opened locked test can support the final confirmatory
claim.

The prepared locked-test v3 protocol (not yet opened) crosses
`sortation_small_kiva` and `warehouse_60x100_kiva`, the same two densities and
three workloads, 30 root seeds, and all 13 registered methods: 4,680 runs in
total. A malformed two-line header in the warehouse map was repaired before any
locked seed was touched; its 60-by-100 grid payload is unchanged and the repaired
file is hash-locked. The earlier protocol's gradual-drift workload is explicitly
outside v3 because no gradual absolute-release treatment was frozen in
validation; no result from this study may claim gradual-drift coverage.

### 4.3 Registered 13-controller family

The formal family contains 13 controllers: the two focal methods, schedule and
signal baselines, and route-feature ablations. Every learned-guidance arm shares
the mandatory bootstrap.

| Controller | Post-bootstrap rule | Budget semantics |
|---|---|---|
| `uniform` | Uniform edge weights; no generator | 0 calls |
| `bootstrap_only` | Hold the bootstrap graph | 0 post calls |
| `always` | Generate every eligible window | Exact 99 |
| `exact_even_B25` | 25 evenly spaced generations | Exact 25 |
| `period_80` | Generate on nominal 80-step buckets | 24 at $H=2000$ |
| `random_B25` | 25 seed-keyed random eligible windows | Exact 25 |
| `js_B25` | Active-goal JS since last publication, with exact-quota pacing | Exact 25 |
| `js_cap_B25` | Same JS family, but no catch-up or forced fill | At most 25 |
| `throughput_drop_B25` | Recent throughput drop plus 0.25 wait ratio | Exact 25 |
| `proposed_no_cohort_B25` | Goal/flow/throughput/wait/age composite | Exact 25 |
| `proposed_cohort_B25` | Previous composite plus route maturity, cohort service, and route-build rate | Exact 25 |
| `causal_block_B25` | Release-only causal score moves one token within each even bucket | Exact 25 |
| `context_memory_B25` | Causal three-action selective memory | At most 25 switches and generations |

Score-based exact policies have a hard prefix envelope and a final feasibility
guard; their exact count is therefore auditable and not an accidental average.
Method order is randomized using a stream independent of task, planner, and
publication-policy randomness.

`random_memory_B25` is not in this family. It is retained only to reproduce the
negative development ablation in Section 5.2 and is rejected by validation-v2
and locked-test runners.

### 4.4 Metrics and root-seed-cluster inference

The primary outcome is scored throughput, $C(H)/2000$; because $H$ is fixed,
tables may report the equivalent completed-task count. Secondary outcomes are
post-bootstrap effective switches, fresh generator calls, reactivations,
completion trajectory/AUC, route-version exposure, cohort service time,
generator time, planner time, waits, and all integrity failures.

The independent unit is the **root seed**, not a window, task, agent, workload,
or map cell. For method $A$ and comparator $B$, the seed-level relative effect
averages equally over the 12 map--density--workload cells,

\[
 d_i=\frac1{12}\sum_{c=1}^{12}
 \frac{q_{A,i,c}-q_{B,i,c}}{q_{B,i,c}}.
\]

We report mean effect, median effect, win rate, and every $d_i$. A percentile
cluster bootstrap resamples whole root seeds 10,000 times with RNG seed
20260714. The one-sided paired sign-flip test is exact when the number of
nonzero root-seed effects permits enumeration. Secondary comparison families
use Holm correction. No window- or task-level pseudo-replication is allowed.

The two preregistered validation gates target different claims:

- **Causal quality:** `causal_block_B25` versus `exact_even_B25` must reach at
  least +2% mean relative effect, a cluster-CI lower bound above zero, one-sided
  $p<.05$, at least 60% root-seed wins, positive effects on both maps and at
  least two workloads, stationary degradation no worse than -1%, and a
  random-B25 noninferiority lower bound above -1%.
- **Context efficiency:** `context_memory_B25` versus `bootstrap_only` must
  reach at least +2%, a cluster-CI lower bound above zero, one-sided $p<.05$,
  at most five mean post-bootstrap switches, at least 80% fewer B25 generator
  calls, an undominated tasks--calls point, and positive effects on both maps.
  “Near exact” language additionally requires a mean effect versus
  `exact_even_B25` no worse than -0.5% and a CI lower bound above -1%.

A scoped “best evaluated controller” statement additionally requires rank one
by validation mean and a multiplicity-adjusted 95% CI lower bound above zero
against the runner-up. Even if passed, this statement is restricted to the
frozen OnlineGGO backbone and evaluated controller family, not global MAPF SOTA.

Concurrent multi-job runs provide no timing evidence. The 80% generator-time
condition is evaluated by a separately frozen `jobs=1` protocol on development
seeds 17--21. It runs only `exact_even_B25` and `context_memory_B25`, strictly
serially, over the same four map--density cells and three workloads (120 runs).
Both the pooled generator-seconds reduction and the mean reduction across 60
paired cells must be at least 80%. These artifacts are timing-only and cannot
be used for throughput inference or controller ranking.

### 4.5 Safety, pairing, and attribution audit

An artifact is complete only when all of the following hold for every paired
arm:

- identical map, root seed, start vector, absolute task-tape SHA-256/FNV
  identity, release projection, and workload manifest;
- zero online workload RNG draws, no tape exhaustion, monotone per-agent
  assignment/completion prefixes, and reward sum equal to completed tasks;
- zero vertex collisions, edge swaps, invalid moves, endpoint mismatches,
  route-trace errors, and budget errors;
- contiguous task and route event identities, valid route-build reasons, and
  completion-to-route cohort attribution; and
- exact or capped publication semantics and generator-call accounting as
  registered for the method.

Planner timeouts remain method outcomes. If the pinned backend aborts or may
have advanced state before an exception, the runner refuses to emit a complete
artifact; it never splices a run or silently deletes a losing arm. Raw and
applied guidance hashes, checkpoint hashes, map hashes, simulator hash, policy
timeline, and safety counters are archived with every run.

## 5 Results

### 5.1 Development screening on the full 13-controller family

The completed development screen contains 390 paired runs: 13 controllers,
ten root seeds (17--26), and three workloads on
`warehouse_small_narrow_kiva` with 400 agents, $H=2000$, and $D=20$. It uses the
frozen 10k generator and absolute-release tapes. Pairing, safety, budget, and
route-attribution audits all pass. These results selected and froze treatments;
they are not fresh-validation or confirmatory evidence.

| Rank | Controller | Mean tasks | Post-bootstrap switches | Total generator calls |
|---:|---|---:|---:|---:|
| 1 | `random_B25` | 4262.30 | 25.00 | 26.00 |
| 2 | `causal_block_B25` | 4238.33 | 25.00 | 26.00 |
| 3 | `proposed_no_cohort_B25` | 4209.23 | 25.00 | 26.00 |
| 4 | `context_memory_B25` | 4195.20 | 3.90 | 4.73 |
| 5 | `js_B25` | 4186.10 | 25.00 | 26.00 |
| 6 | `proposed_cohort_B25` | 4172.73 | 25.00 | 26.00 |
| 7 | `period_80` | 4171.07 | 24.00 | 25.00 |
| 8 | `exact_even_B25` | 4169.77 | 25.00 | 26.00 |
| 9 | `js_cap_B25` | 4163.83 | 20.53 | 21.53 |
| 10 | `throughput_drop_B25` | 4156.63 | 25.00 | 26.00 |
| 11 | `always` | 4151.57 | 99.00 | 100.00 |
| 12 | `bootstrap_only` | 4070.47 | 0.00 | 1.00 |
| 13 | `uniform` | 2444.33 | 0.00 | 0.00 |

The two focal controllers exhibit different development trade-offs.
`causal_block_B25` improves over equal-count even scheduling by 68.57 tasks
(+1.64%); the root-seed-cluster 95% interval is [10.37, 136.07], with 7/10
seed-cluster wins and exploratory one-sided exact $p=.0264$. This raw
development comparison does not survive Holm correction across all method
comparisons ($p_{Holm}=.1582$). Its workload gains over exact-even are +83.9
(stationary), +68.7 (abrupt), and +53.1 (recurrent) tasks. It remains 23.97
tasks below `random_B25` on average, with 95% CI [-110.57, 57.37].

`context_memory_B25` improves over bootstrap-only by 124.73 tasks (+3.06%),
with cluster 95% CI [59.20, 194.77] and 9/10 root-seed wins. Relative to
`exact_even_B25`, it is +25.43 tasks (+0.61%), but the interval
[-85.17, 139.03] is inconclusive. Relative to the throughput-leading
`random_B25`, it is -67.10 tasks (-1.57%), with interval [-145.07, 10.20]. Its
4.73 total generator calls are 81.8% fewer than the 26 calls of the exact-B25
arms. The development tasks--calls Pareto frontier is therefore
`bootstrap_only`--`context_memory_B25`--`random_B25`.

This is call-efficiency evidence only. The development matrix ran concurrent
jobs, so its `generator_seconds` cannot establish runtime efficiency; the
planned `jobs=1` exclusive timing comparison was not run after the candidate
failed validation-v2, and no runtime-efficiency claim is made.

These data motivate both preregistered validation questions, but they do not
support a pure-throughput-best or SOTA claim: random scheduling ranks first,
and uncertainty among the leading controllers is substantial.

### 5.2 Negative ablation: random opportunities plus naive context recall

We also tested `random_memory_B25`, which shares all 25 opportunity flags
bit-for-bit with `random_B25` and changes only the action at an accepted
opportunity: recall the nearest matching historical context when available,
otherwise generate. This is a paired mechanism ablation, not a formal
validation candidate.

Across 30 development runs, memory minus random is +0.03 task (+0.001%), with
root-seed-cluster 95% CI [-24.10, 24.40] and exact two-sided $p=1$. Recall
fires only 3 times in 750 opportunities (0.4%), saving 3 of 780 generator calls
(0.385%). The three interventions have mixed effects (-239, -6, and +246
tasks), while all 27 non-recall cells reproduce identical task counts. This
negative result shows that nearest-context recall grafted onto random timing is
too sparse and unstable; it does not justify adding the ablation to fresh
validation. The implementation remains available solely for reproduction.

### 5.3 Fresh validation-v2 results

All four protected artifacts completed: 13 controllers were evaluated over ten
fresh root-seed clusters and 12 map--density--workload cells, for 1,560 runs.
The combined audit found zero safety, route-attribution, budget, planner-timeout,
or pairing failures. Inference therefore retains all runs and treats the ten
root seeds, rather than the 120 scenario cells, as independent observations.

| Frozen comparison | Mean relative effect | 95% root-cluster CI | W/T/L roots | One-sided $p_{Holm}$ | Map directions | Workload directions (A/R/S) |
|---|---:|---:|---:|---:|---|---|
| `causal_block_B25` minus `exact_even_B25` | +0.10% | [-0.58%, +0.71%] | 7/0/3 | .7617 | +/+ | +/+/- |
| `causal_block_B25` minus `random_B25` | -0.07% | [-0.87%, +0.85%] | 4/0/6 | .7617 | -/+ | +/-/- |
| `context_memory_B25` minus `bootstrap_only` | +5.30% | [+3.69%, +7.28%] | 10/0/0 | .0020 | +/+ | +/+/+ |
| `context_memory_B25` minus `exact_even_B25` | +0.03% | [-0.57%, +0.59%] | 4/0/6 | .4678 | -/+ | +/-/+ |

Here map directions are ordered as `warehouse_small_kiva`/`warehouse_small_narrow_kiva`,
and A/R/S denotes abrupt/recurrent/stationary. The reported $p$ values are
Holm-adjusted one-sided exact sign-flip tests within the preregistered comparison
families.

The causal-quality gate fails: the effect over exact-even is far below the
preregistered +2% threshold, its interval includes zero, and its one-sided test
is not significant. The context controller passes every preregistered
performance condition: it improves over bootstrap-only on both maps and all
three workloads, remains on the tasks--calls Pareto frontier, and satisfies the
near-exact gate against `exact_even_B25`. Its mean is 4,475.86 tasks with 6.158
post-bootstrap switches and 5.483 total generator calls. The latter is a 78.91%
reduction from the 26-call B25 reference, narrowly below the required 80%, while
the switch mean narrowly exceeds the cap of 5. These two resource conditions
make the overall context candidate gate fail despite its held-out performance.

`proposed_cohort_B25` has the highest validation mean (4,523.90 tasks), ahead of
`js_B25` (4,505.92) by +0.48% in the root-cluster comparison. The
multiplicity-adjusted 95% interval [-0.53%, +1.57%] includes zero
($p_{Holm}=.252$), so rank one does not support a ``best evaluated controller''
claim. The preregistered recommendation is consequently
`NO_GO_RETURN_TO_DEVELOPMENT`, not a SOTA result.

### 5.4 Development repair and unopened confirmatory tests

Because the validation candidate gate failed, the exclusive `jobs=1` timing
protocol was not run; concurrent `generator_seconds` remain diagnostic only.
Locked-test v3 and seeds 1001--1030 remain sealed and must not be opened for the
failed treatment.

The next proposed controller is the development-only
`context_dualcap_G4S5`: it retains the context-memory decision rule but hard-caps
post-bootstrap fresh generations at four and effective switches at five (at
most five total generator calls including bootstrap). This construction targets
the two narrowly missed resource gates directly. Its throughput, recall, and
robustness results are not yet available and are not evidence in this paper.
Only a newly frozen candidate that passes a new fresh validation protocol could
justify opening a locked test. No global or scoped SOTA claim is currently
authorized.
