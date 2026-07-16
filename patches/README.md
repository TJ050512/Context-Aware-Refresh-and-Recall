# OnlineGGO patch provenance

The claim-bearing experiments use a locally modified OnlineGGO checkout. To
avoid committing a nested Git repository, this repository records the changes
as a patch against the exact upstream revision below.

- Upstream: <https://github.com/zanghz21/OnlineGGO.git>
- Pinned revision: `ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256`
- Local changes: `onlineggo-local.patch`
- Additional experiment configs: `onlineggo_configs/`
- Upstream license copy: `OnlineGGO-LICENSE`

From the repository root, reconstruct the checkout with:

```bash
bash scripts/setup_onlineggo.sh
```

The setup script refuses to overwrite an existing checkout. The patch is a
source snapshot for reproducibility; keep future OnlineGGO changes in a
separate commit or regenerate the patch deliberately against a recorded
upstream revision.
