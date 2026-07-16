# Frozen OnlineGGO CNN checkpoint contract

The pinned source is OnlineGGO commit
`ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256`. Period-online configs with a
six-channel observation declare exactly 3,084 learned values:

| block | shape | values |
|---|---:|---:|
| Conv2d weight/bias, 6 to 32, 3 by 3 | `(32,6,3,3)` and `(32,)` | 1,760 |
| BatchNorm affine, 32 channels | two times `(32,)` | 64 |
| Conv2d weight/bias, 32 to 32, 1 by 1 | `(32,32,1,1)` and `(32,)` | 1,056 |
| BatchNorm affine, 32 channels | two times `(32,)` | 64 |
| Conv2d weight/bias, 32 to 4, 1 by 1 | `(4,32,1,1)` and `(4,)` | 132 |
| BatchNorm affine, 4 channels | two times `(4,)` | 8 |
| **Total** | | **3,084** |

The official evaluator constructs `CNNUpdateModel` and never calls
`model.eval()`. Therefore its BatchNorm layers use the current observation's
spatial statistics even inside `torch.no_grad()`. The frozen loader preserves
that behavior. Switching it to evaluation mode is not an innocuous cleanup;
it changes the policy output.

Validate a checkpoint before any rollout:

```bash
python scripts/verify_frozen_cnn_checkpoint.py \
  /absolute/path/to/optimal_update_model.json \
  --expected-file-sha256 <64-hex-file-hash>
```

The verifier prints both the exact file hash and a whitespace-independent hash
of the effective little-endian float32 parameter vector. It then compares the
independent loader and the pinned official class on a deterministic nontrivial
six-channel observation; acceptance requires a `[4,H,W]` result and bitwise
identical values.

Use it in the publication-schedule runner only after verification:

```bash
python scripts/gate0_publication_mvp.py \
  --generator-mode frozen_cnn \
  --checkpoint /absolute/path/to/optimal_update_model.json \
  --checkpoint-sha256 <64-hex-file-hash> \
  --methods uniform never always period_100 task_js_event oracle_shift \
  --seeds 20 21 22 \
  --output results/official_gate0/learned_cnn_mvp.json
```

The pinned authors' repository publishes no trained
`optimal_update_model.json`; a locally trained checkpoint must therefore be
identified by its training provenance and both hashes. Synthetic weights are
valid only for loader equivalence tests and must never be reported as a
learned baseline.

Here `uniform` makes zero generator calls and retains the all-ones guidance
installed at reset. `never` is deliberately different: it publishes the CNN
once at the first decision and then reuses that learned graph. Thus `uniform`
is the no-learned-guidance baseline and `never` is the bootstrap-only learned
baseline.
