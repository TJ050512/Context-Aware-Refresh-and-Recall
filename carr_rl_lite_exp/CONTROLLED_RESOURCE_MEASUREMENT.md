# Controlled resource measurement (supplementary, post-confirmatory)

This note archives a controlled wall-clock microbenchmark of the guidance
refresh pipeline, measured after the frozen Experiment B matrix. It shows what
the paper's logical generator-call resource does and does not represent on the
evaluation host. The benchmark extends the earlier
`timing_evidence_valid=false` diagnostic with a serial measurement for which
`timing_evidence_valid=true`.

> **Scope and headline.** The frozen CNN contains only 3,084 parameters, and a
> forward call is very cheap on this host: the unweighted mean of the six
> run-level `generator_seconds / total_generator_calls` values is 1.83 ms
> (median 1.60 ms; the pooled ratio is 1.66 ms). Logical-call reduction is
> therefore not an equal reduction in end-to-end wall-clock time. In this
> benchmark, simulator execution and uninstrumented orchestration/context
> bookkeeping dominate CNN inference. CARR controls refresh timing under a
> call quota; it is not presented as a physical-resource optimizer.

## Method

- **Runner:** frozen v1 runner with `--jobs 1 --exclusive-timing`; arms run
  serially in fresh processes with numerical-library threads pinned to one.
  The enclosing process was restricted to CPU cores 0--3.
- **Scenario:** `narrow_r020` (218 agents), abrupt workload, development seeds
  17 and 18, and the frozen 20k checkpoint
  `optimal_update_model_20000.json`.
- **Methods:** `context_memory_B25` (CARR),
  `context_no_reactivation_B25` (NoRecall), and `exact_even_B25` (dense
  reference).
- **Instrumentation:** `time.perf_counter_ns` records `generator_seconds`
  (CNN forward), `simulator_seconds` (GPIBT simulator), and `elapsed_seconds`
  (end-to-end wall clock).

This is a deliberately small, development-only microbenchmark: two runs per
method, six runs in total, on one scenario and workload. All summaries are
descriptive. The archived median and P90 values are included for completeness,
not as inferential or tail-latency claims.

## Results

Means are over the two runs for each method. Calls include the mandatory
bootstrap generation.

| Method | Calls | Generator only (s) | Simulator (s) | End to end (s) |
|---|---:|---:|---:|---:|
| CARR | 8.00 | 0.0214 | 6.383 | 13.97 |
| NoRecall | 10.00 | 0.0141 | 5.228 | 11.69 |
| Exact-B25 | 26.00 | 0.0377 | 5.349 | 12.68 |

- CARR's mean generator-only time is **43.3% lower** than Exact-B25's.
- CARR's mean end-to-end time is **10.2% higher** than Exact-B25's
  (13.97 s versus 12.68 s).
- In this six-run microbenchmark, CARR makes 8.00 versus 26.00 calls, or 69.2%
  fewer. The paper's approximately 79% call reduction is the mean over the
  complete 3,840-run Experiment B matrix and must not be substituted for this
  microbenchmark-specific count.

The generator-only decrease is smaller than the logical-call decrease because
per-call timing varies across these six short runs. NoRecall also illustrates
that call count alone does not determine measured generator time at this
sample size.

## Interpretation

1. A logical generator call is an exogenous quota unit. It can model, for
   example, a remote guidance service with a call limit, a per-call generative
   service, or a refresh requiring separate certification.
2. On this small-CNN backbone it is **not** a validated proxy for wall-clock,
   GPU, energy, or monetary savings. Fewer calls mean fewer invocations, not a
   proportional reduction in physical compute.
3. These post-confirmatory measurements do not alter Experiment B, its primary
   non-inferiority result, or its multiplicity-controlled secondary analyses.
   They only quantify the resource-claim boundary already stated in the paper.

## Files and verification

- `results/carr_rl_lite/microbench_summary.json`: aggregate metrics and
  estimator definitions.
- `results/carr_rl_lite/microbench_narrow_r020.csv`: compact run-level records,
  including generation, recall, publication, and timing counters.
- `results/carr_rl_lite/microbench_narrow_r020.json`: sanitized full run
  records, environment versions, source hashes, and protocol metadata.

From the repository root, the standard-library verifier independently
recomputes the aggregate values, checks CSV/JSON counter agreement, verifies
the SHA-256 manifest, and scans the public results for machine-specific paths:

```bash
python3 carr_rl_lite_exp/scripts/verify_public_summaries.py
```

## Hardware and execution boundary

The measurement used an anonymous Linux x86-64 evaluation host reporting 128
logical CPUs. PyTorch 1.13.0 was restricted to one intra-op and one inter-op
thread, and common BLAS thread variables were set to one. The frozen evaluator
uses a CPU inference path; available GPUs were not used. Machine-specific host
names and absolute paths have been removed from the public JSON while source
content hashes and repository-relative paths are retained.
