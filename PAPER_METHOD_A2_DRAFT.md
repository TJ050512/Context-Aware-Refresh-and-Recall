# Method Draft: Budgeted Context-Memory for Multi-Agent Guidance Publication

> **Internal evidence note (remove before submission).** This text describes
> the frozen A2 method and protocol, not a positive-result claim. The final A2
> analyzer assigned `TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER`. Accordingly,
> the paper must not call the method SOTA, claim universal superiority, or say
> that historical reactivation was beneficial. The defensible scope is a
> transparent, audited study of resource-aware guidance publication on one
> frozen OnlineGGO/GPIBT backbone.

## 3. Method

### 3.1 Problem setting

We study lifelong multi-agent path finding (LMAPF) on a directed grid graph
$G=(V,E)$. A team of $n$ agents repeatedly receives pickup-and-delivery tasks.
At every simulator step, an agent either waits or traverses an adjacent edge;
vertex collisions and opposing edge swaps are forbidden. The planner uses a
shared directed-edge guidance tensor when constructing routes. This shared
guidance is a coordination artifact for the multi-agent system: it can alter
future route choices across the fleet, but it does not retroactively rebuild
routes already in execution.

A frozen convolutional generator $F_\theta$ maps the causal traffic observation
at decision $k$ to a raw four-channel edge-weight tensor,

$$
    w_k=F_\theta(o_{\le t_k})\in\mathbb{R}^{4\times H_m\times W_m}.
$$

The OnlineGGO environment masks invalid edges and normalizes $w_k$ before the
GPIBT backend consumes it. The experiment varies only the policy deciding when
to keep, replace, or recall guidance; generator weights, planner, simulator,
maps, and workloads are shared by every method.

Each episode has a 200-step warm-up and a scored horizon $H=2000$. Guidance
decisions occur every $D=20$ steps, giving $N=100$ scored windows. Every method
makes one mandatory generator call at decision 0. This bootstrap is outside
the post-bootstrap budget, leaving $K=N-1=99$ eligible decisions. We define

$$
    B_{25}=\left\lceil 0.25K\right\rceil=25.
$$

Let $C_\pi$ be the number of tasks completed during the scored horizon, $G_\pi$
the number of post-bootstrap fresh generator calls, and $S_\pi$ the number of
effective post-bootstrap guidance installations. The study compares the
throughput--resource trade-off $(C_\pi,G_\pi,S_\pi)$ under registered caps; it
does not optimize or retrain $F_\theta$ on the confirmation roots.

### 3.2 Exogenous absolute-release workloads

Completion-driven task generation would couple workload difficulty to policy
speed: a faster method could advance the task RNG sooner and receive different
future goals. We remove this feedback by materializing the complete task tape
before timestep zero. For agent $i$,

$$
    \mathcal{T}_i=((g_{i,0},r_{i,0}),\ldots,(g_{i,L_i-1},r_{i,L_i-1})),
$$

where $g_{i,j}$ is a goal and $r_{i,j}$ is an absolute release time. Releases
enter a per-agent FIFO queue; a busy agent may accumulate tasks. Release times
are deterministically staggered with interval 110 per agent, and four
non-scoring guard tasks per agent prevent finite-tape exhaustion. Starts,
goals, releases, and task identifiers are identical across paired methods and
are verified by independent SHA-256 and C++ FNV-1a fingerprints.

We use stationary, abrupt, and recurrent workloads. Dynamic workloads change
endpoint distributions at scored offsets 500, 1000, and 1500; recurrent uses
an $A\rightarrow B\rightarrow A\rightarrow B$ sequence. Adjacent distributions
have Jensen--Shannon (JS) divergence at least 0.30 under $\sigma=0.75$. Phase
centres, phase clocks, and unreleased tape suffixes are audit-only and are
never controller inputs.

### 3.3 Guidance generations, installations, and delayed fleet adoption

We distinguish a **generation ID** from an **installation version**. A
generation ID identifies one immutable output of $F_\theta$ and remains fixed
when that graph is recalled. An installation version increments whenever a
new or historical graph becomes the active coordination signal. A hold still
advances the simulator and planner: the adapter sends a defensive copy of the
cached raw tensor to `env.step`. Reusing an already normalized tensor is
forbidden because the environment would normalize it twice.

Guidance affects an agent only when a route is actually constructed. We
therefore log route-build events with task, agent, timestep, installation
version, raw/applied hashes, and build reason. For the active version $v_k$,
the route-adoption fraction is

$$
 m_k^{\mathrm{route}}=
 \frac{\#\{\text{active agents whose latest route uses }v_k\}}
      {\#\{\text{active agents}\}}.
$$

This delayed, heterogeneous adoption is central to the distributed/agentic AI
interpretation: a global control-plane update is not an instantaneous state
change for all agents. Publication policies must allow the fleet to adopt an
installation before another one is issued.

### 3.4 Causal event signal

At each decision, goals released during the latest trace window are binned
into a $4\times4$ spatial histogram with 0.5 pseudocount per bin. Windows with
no release are marked missing. Let $p_k^f$ be the mean of non-missing
histograms in the latest two windows and $p_k^s$ the mean of up to six
preceding non-missing windows. The normalized change score is

$$
 z_k=\operatorname{JS}(p_k^f,p_k^s)/\log 2\in[0,1],
$$

and is zero if either side is unavailable. This signal uses only events that
have already occurred; it excludes latent phase metadata, future goals, and
future rewards. Thresholds are computed from past score history before the
current score is appended.

### 3.5 Context-Memory controller

`context_memory_B25` treats generated guidance as a reusable catalog. Its
action space is

$$
 a_k\in\{\textsc{hold},\textsc{reactivate}(j),\textsc{generate}\}.
$$

For each generation $j$, the controller stores the causal $4\times4$
distribution $c_j$ of currently active task goals at generation time. Given
current context $c_k$, define

$$
 d_{k,j}=\operatorname{JS}(c_k,c_j)/\log 2.
$$

Let $a$ denote the active generation and $j^*$ the nearest non-active catalog
entry. Recall is available when

$$
 d_{k,j^*}\le0.05
 \quad\text{and}\quad
 d_{k,a}-d_{k,j^*}\ge0.02.
$$

The operation priority is: reactivate an available historical match; otherwise
generate if maintenance is due; otherwise hold if the active context matches;
otherwise propose a fresh generation. Maintenance is due after 25 windows of
guidance age when $z_k\le0.20$.

An available operation is executed only when maintenance is due or the event
signal is both at least 0.10 and strictly above the historical 75th percentile
after four history observations. It must also satisfy
$m_k^{\mathrm{route}}\ge0.5$, a six-window minimum gap, at least three remaining
effect windows, and the unspent cap. Persistence is one window. There is no
catch-up or forced fill.

Both effective switches and fresh generations are capped at $B_{25}$.
Reactivation consumes one switch token but no generator token; generation
consumes both. Including bootstrap, total generator calls are
$1+G_\pi$. The controller has no per-run six-call cap: its actual call
distribution must be reported, not described as a strict equal-budget G5
comparison. A recall of the already active or hash-identical graph is reduced
to a hold.

### 3.6 Registered comparisons

The frozen family contains exactly eight methods:

| Method | Role | Post-bootstrap contract |
|---|---|---|
| `bootstrap_only` | No-online-update baseline | Hold bootstrap guidance; 0 calls |
| `exact_even_G4` | Five-total-call fixed baseline | 4 calls at decisions 25, 50, 75, 99 |
| `exact_even_G5` | Six-total-call fixed baseline | 5 calls at decisions 20, 40, 60, 80, 99 |
| `random_G5` | Timing-control baseline | 5 precommitted root-keyed random calls |
| `js_cap_G5` | Simple adaptive baseline | Active-goal JS trigger; at most 5 calls, no forced fill |
| `context_no_reactivation_B25` | Memory ablation | Same context policy and B25 cap, but historical recall is unavailable |
| `context_memory_B25` | Focal controller | Hold/reactivate/generate; at most 25 switches and generations |
| `exact_even_B25` | High-call reference | Exactly 25 evenly spaced calls; 26 including bootstrap |

For an exact budget $B$, global decision $d\in\{1,\ldots,99\}$ publishes iff

$$
 \left\lfloor dB/99\right\rfloor>
 \left\lfloor(d-1)B/99\right\rfloor.
$$

`random_G5` uses an RNG stream independent of starts, tasks, planner state,
method order, and all controller streams. `js_cap_G5` uses active-goal JS since
the last publication, a past-score 75th percentile, a two-window gap, and a
three-window effect horizon. The no-reactivation ablation changes only recall
availability; it preserves maintenance, context matching, event thresholds,
route maturity, gaps, and budget logic. Thus the comparisons separately probe
whether online updates matter, whether sparse timing matters, and whether the
catalog/recall branch adds value. These are hypotheses tested by the matrix,
not conclusions assumed by the method.

## 4. Preregistered A2 Evaluation and Audit

### 4.1 Frozen matrix and estimand

All arms use the frozen 3,084-parameter OnlineGGO CNN checkpoint and pinned
GPIBT simulator binary. We cross two warehouse maps with two agent densities:

| Scenario | Map | Agents |
|---|---|---:|
| `narrow_r020` | `warehouse_small_narrow_kiva` | 218 |
| `narrow_r035` | `warehouse_small_narrow_kiva` | 382 |
| `regular_r020` | `warehouse_small_kiva` | 255 |
| `regular_r035` | `warehouse_small_kiva` | 447 |

A2 uses ten roots derived before execution from the effect-blind A1 incident
record: `[691817, 376110, 263001, 293231, 296805, 274330, 997942, 319782,
807287, 326454]`. The complete design is $8$ methods $\times10$ roots
$\times3$ workloads $\times4$ scenarios, or 960 mandatory arms. The
independent unit is the root. Each root-level relative effect averages the 12
scenario--workload cells equally:

$$
 d_i(A,B)=\frac1{12}\sum_c
 \frac{C_{A,i,c}-C_{B,i,c}}{C_{B,i,c}}.
$$

Intervals use 10,000 whole-root bootstrap samples with seed 20260715.
Superiority uses exact one-sided paired sign-flip tests, with Holm correction
for the six registered focal comparisons. The separate comparison with
`exact_even_B25` tests a preregistered 1% non-inferiority margin. No task,
window, agent, or run is treated as an independent replicate.

### 4.2 Fresh-process and one-shot protocol

Every arm runs in a fresh OS process. A process instance is identified by
`(host, child PID, process_start_ns)` and a canonical run UUID; bare PID values
are not required to be globally unique because operating systems recycle
them. Child and parent PIDs must differ. Each append-only ledger contains one
started and one completed event per frozen arm and binds its identity, host,
process instance, UUID, safety state, and canonical run hash. The four ledgers
must cover the exact 960-arm Cartesian product without deletion, replacement,
retry concealment, or overwrite.

The A1 matrix was excluded effect-blind after an erroneous bare-PID uniqueness
gate encountered legal PID recycling. A2 changed only the root vector,
non-causal provenance metadata, and process-identity predicate; it did not
change behavior, comparator, map, workload, budget, estimand, or analysis.
A1 outcomes are not pooled with or used to interpret A2.

The matrix runs on one attested host. Immediately before opening A2 roots, the
launcher rechecks the sealed environment digest, host-instance fingerprint,
ordered GPU UUID/name/driver/VBIOS inventory, Python/PyTorch/NumPy and native
runtime projection, and single-thread settings. Source files, checkpoint,
maps, simulator, protocols, launcher, analyzer, and tests are bound by
SHA-256. Outcomes, effects, ranks, and provisional p-values are not inspected
until all 960 arms pass integrity checks; the frozen analyzer is then run once.

### 4.3 Pairing, safety, and non-anticipation audit

For every paired cell, the audit requires identical starts, task-tape SHA/FNV,
release projection, map, workload manifest, and reset observation. It verifies
zero online workload RNG draws, no tape exhaustion, monotone task identities,
reward/completion conservation, exact method budgets, and independent task,
planner, publication, and method-order RNG streams. Executed paths are replayed
to check zero vertex collisions, edge swaps, invalid moves, and endpoint
mismatches. Raw and applied guidance hashes, installation versions, route
builds, and generation/reactivation conservation are retained. A future-suffix
metamorphic test additionally requires that changing only unreleased future
tasks cannot alter any earlier observation, score, decision, action, or hash.

### 4.4 Scope and distributed-AI relevance

This is a controlled study of adaptive coordination in a multi-agent system.
Its central systems question is when a shared learned coordination artifact
should be recomputed or reused when agents adopt it asynchronously and
generation is costly. Context-Memory supplies an auditable control plane for
that question, while the route-cohort instrumentation exposes delayed uptake
that would be hidden by an instantaneous-update abstraction.

The evaluation does **not** establish global LMAPF SOTA: it fixes one learned
generator, one GPIBT-style backbone, two warehouse maps, and three workload
families. Any claim must remain a same-backbone, evaluated-controller claim and
must follow the mechanically assigned A2 outcome, including negative and
failed contrasts.
