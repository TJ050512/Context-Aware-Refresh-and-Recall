# Selective-repair development sweep

> Development seeds only; no inferential claim may use this table.

| scale | delay | lazy-no-update | all-lazy | top-random | viable |
|---:|---:|---:|---:|---:|:---:|
| 2.0 | 0 | +0.0733 | +0.0133 | +0.0304 | True |
| 2.0 | 20 | +0.0600 | +0.0167 | -0.0312 | False |
| 2.0 | 40 | +0.0392 | +0.0483 | -0.0200 | False |
| 3.0 | 0 | +0.0650 | +0.0058 | -0.0608 | False |
| 3.0 | 20 | +0.0350 | -0.0450 | -0.0454 | False |
| 3.0 | 40 | +0.0567 | -0.0183 | -0.0442 | False |
| 5.0 | 0 | +0.0850 | -0.0458 | -0.0750 | False |
| 5.0 | 20 | +0.0975 | +0.0117 | -0.0638 | False |
| 5.0 | 40 | +0.0833 | -0.0358 | -0.0308 | False |
| 8.0 | 0 | +0.1400 | -0.0475 | -0.0737 | False |
| 8.0 | 20 | +0.0875 | +0.0083 | -0.0579 | False |
| 8.0 | 40 | +0.1208 | -0.0408 | -0.0229 | False |

Recommended frozen setting: `{'guidance_scale': 2.0, 'event_delay': 0, 'viable': True, 'lazy_vs_no_update_post_absolute': 0.07333333333333332, 'all_vs_lazy_post_absolute': 0.013333333333333341, 'top_vs_random_post_absolute': 0.030416666666666647, 'top_vs_random_total_absolute': 0.009166666666666703, 'mean_lazy_post': 0.35333333333333333, 'mean_all_post': 0.3666666666666667, 'mean_top_post': 0.4066666666666667, 'mean_random_post': 0.37625}`
