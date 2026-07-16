# 深度研究交接：预算约束下的因果 Guidance Publication

更新时间：2026-07-14 16:10 CST  
目标会议：DAI 2026 Research Track  
证据状态：开发与 validation-v2；locked test 尚未解封；不得据此声称 global LMAPF SOTA。

## 1. 希望外部研究模型回答什么

请把本项目视为一个机制研究问题，而不是要求为既定方案背书：

> 在冻结的 OnlineGGO-style `[p-on]+GPIBT` backbone 上，能否仅使用因果可观测量，在非平稳 lifelong MAPF 中决定何时生成、复用或重新激活全局 guidance graph，并以不超过 6 次总 CNN 调用获得接近 exact-even-B25 的吞吐？

请重点回答：

1. 当前瓶颈的最可信机制解释是什么？请区分由数据直接支持的解释与推测。
2. `context_eventreserve_G5S6` 是否合理，是否明显过拟合于上一轮 120 paired cells？
3. 若该候选仍未通过，下一步应优先修改 action space、trigger、context representation、budget allocation，还是把论文重构为 Pareto/measurement 论文？
4. 在保持完全因果、总 generator calls 不高于 6、平均 post-bootstrap switches 不高于 5 的约束下，请提出最多 3 个可证伪的新机制，每个机制给出精确定义、预期改善、失败模式和最小实验。
5. 现有贡献是否足以构成 DAI Research Track 论文？最强安全 claim、必须补的 baseline、ablation 和统计检验分别是什么？
6. 如果目标改成 global LMAPF SOTA，哪些公开 solver 必须公平移植？若时间有限，哪个外部 baseline 的信息增益最高？

请不要建议查看 locked seeds、放宽既定 gate、事后删除不利场景，或把 development 结果写成 confirmatory evidence。

## 2. 问题与协议

- 固定 backbone：adapted frozen 10k CNN guidance checkpoint + compiled GPIBT simulator。
- 每个 episode：warm-up 200；scored horizon 2000；decision window 20；100 个 scored windows。
- decision 0 为 mandatory bootstrap，不计 post-bootstrap cap。
- 主 exact comparator：`exact_even_B25`，99 个 eligible decisions 中精确发布 25 次，因此总 generator calls=26。
- workload：stationary、abrupt、recurrent；任务和绝对 release time 在运行前生成完整 tape，各方法共享 starts、tasks、releases、task IDs。
- 场景：2 maps × 2 densities；10 root seeds；每方法 120 paired cells，但推断单位是 10 个 root clusters，而非 120 个 cells。
- 主要完整性要求：零 collision/edge swap/invalid move、任务 tape identity 一致、release projection 一致、无在线 workload RNG、generator/switch 守恒、预算守恒。

## 3. validation-v2 已知结论

完整设计为 13 methods × 10 roots × 3 workloads × 4 scenarios = 1,560 runs；审计全部通过。

- `context_memory_B25` vs `bootstrap_only`：`+5.3021%`，root-cluster 95% CI `[+3.6918%, +7.2836%]`，10/0/0 roots，Holm-adjusted one-sided p=`0.001953`。
- `context_memory_B25` vs `exact_even_B25`：`+0.03%`，CI `[-0.57%, +0.59%]`；近似 exact，但未形成确认性优势。
- `context_memory_B25` 平均总 generator calls=`5.48`，相对 exact 的 26 次减少 `78.91%`，距离 80% efficiency gate 差 `1.09` percentage points。
- 平均 post-bootstrap switches=`6.158`，未满足平均不高于 5 的 gate。
- throughput 排名第一为 `proposed_cohort_B25`，但未与 runner-up `js_B25` 统计分离。
- 正式 recommendation：`NO_GO_RETURN_TO_DEVELOPMENT`；locked test 保持封存。

这说明研究方向不是无效：低调用 context memory 已接近 exact 且显著优于 bootstrap；真正瓶颈是把资源从约 5.48 calls / 6.16 switches 压到目标内时，不能损失吞吐。

## 4. 第一轮资源约束方法：`context_dualcap_G4S5`

开发设计：4 methods × 10 roots × 3 workloads × 4 scenarios = 480 runs；审计通过。

方法：post-bootstrap fresh generations ≤4；实际 switches ≤5；加 bootstrap 后 total generator calls ≤5。

结果：

- vs bootstrap：`+2.8151%`，CI `[+1.3230%, +4.4509%]`，9/0/1 roots，p(greater)=`0.003906`。
- vs original context：`-0.4625%`，CI `[-0.7928%, -0.1396%]`，3/0/7 roots。
- vs exact：`-1.2573%`，CI `[-1.9510%, -0.5635%]`，1/0/9 roots。
- mean total calls=`4.45`，相对 exact 减少约 `82.9%`；mean switches=`4.3667`。
- recommendation：`NO_GO_COMBINED_DEVELOPMENT_SCREEN_FAILED`。

因此它满足资源目标并显著优于 bootstrap，但没有满足 exact non-inferiority；可以作为 Pareto 点，不能作为当前主方法。

## 5. 轨迹级机制诊断

在上一轮 120 个 paired trajectories 中：

- dualcap 与 original context：71 个 trajectory 分叉，49 个完全相同。
- original context 均值：post generations `4.375`、switches `6.083`、total calls `5.375`。
- 若仅把 generations 截到 5，估计总 calls 约 `4.97`，刚好达到相对 exact 减少 80%。
- original context 的第 5 次 fresh generation 出现在 46/120 runs：44 次为 event-triggered，2 次含 maintenance；30 abrupt、16 recurrent；平均 decision index `68.8`。
- 在这 46 个 runs 中，G4/S5 相对 context 平均少约 `48.13` tasks，root/cell W/T/L=`7/2/37`。这是最大的已识别损失源。
- original context 的第 6 次 switch 出现在 64/120 runs：33 reactivation、29 fresh event generation、另有 2 个 maintenance-related cases。
- `G<5, S≥6` 的 25 个 runs 中，截断到 S5 相对 context 平均约 `+1` task，13/0/12；第 6 次 switch 整体没有稳定价值。
- 首次分叉若是被抑制的 fresh generation：42 个主要 cases，dualcap 相对 context 平均约 `-51` tasks，7/1/34。
- 首次分叉若是 reactivation：25 个主要 cases，平均差约 `+0.24` task，近似中性。

最直接的数据解释：G4 太紧，误删了晚期真实 workload-change generation；S6 中大量 reactivation 不值得保留。但这是同一开发数据上的 post-hoc diagnosis，必须由新开发 screen 后再用 untouched validation 验证。

## 6. 当前候选：`context_eventreserve_G5S6`

精确定义：

- total post-bootstrap fresh generations ≤5，因此含 bootstrap 的 total generator calls ≤6。
- total actual post-bootstrap switches ≤6。
- 前 5 个 switch 仍由原 context-memory controller 决定，reactivation 不消耗 generation cap。
- 当已经执行 5 个 switches 时，第 6 个槽位只允许 fresh `generate`。
- 第 6 个 switch 必须满足：未约束 controller 的 deterministic deep-copy preview 会 accept；`triggered=True`；把 maintenance 关闭后仍会 accept 且 triggered。第 6 次 reactivation 和 maintenance-only generation 均被拒绝。
- preview 不推进 live policy 的 score history、persistence、gap 或 spend；candidate、binding、qualified、execution 分开审计。
- 该方法仅在 `DEVELOPMENT_ONLY_METHODS` 中；正式 13-method family 未改。

设计动机：恢复有价值的第 5 次 late event generation，同时避免把第 6 个 switch 浪费在 reactivation 上。预期 total calls 约 4.97，理论上仍可达到 80% reduction。

最终 development-screen evidence：

- 核心边界测试、off-by-one、maintenance-only、reactivation、守恒测试均通过。
- 600-run development matrix 审计全部通过；正式 recommendation 为 `NO_GO_EVENTRESERVE_DEVELOPMENT_SCREEN_FAILED`。
- vs bootstrap：`+2.90%`，root-cluster 95% CI `[+1.46%, +4.48%]`，9/0/1 roots，Holm p(greater)=`0.007812`。
- vs exact：`-1.17%`，CI `[-1.71%, -0.62%]`，1/0/9 roots。
- vs original context：`-0.37%`，CI `[-0.58%, -0.18%]`，1/0/9 roots。
- vs G4/S5：`+0.10%`，CI `[-0.07%, +0.27%]`，7/0/3 roots；方向正确但幅度很小，且此比较不是硬门槛。
- mean total calls=`4.92`，相对 exact 减少约 `81.1%`；mean post-bootstrap switches=`4.72`，资源门槛均通过。
- 失败门槛：bootstrap 10/10 roots、exact mean non-inferiority、exact CI lower bound。不得进入 validation-v3。

当前最强数据解释：恢复第 5 次 generation 只能从 G4/S5 挽回约 `+0.10%`，无法解决约 `-1.17%` 的 exact gap。瓶颈不是 cap 本身，而是 controller 尚不能可靠预测某次 guidance change 的正/负边际价值，尤其缺乏对 stationary harm 与 workload-change benefit 的区分。

冻结标识：

- `claim_runner.py` SHA-256：`d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e`
- experiment runner SHA-256：`694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50`
- eventreserve config SHA-256：`adda8cf0175ccac6a469e71ead1b3ec66ab96a4cfcd3d6dd98a80e41a4338e86`
- checkpoint file SHA-256：`e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d`
- checkpoint params SHA-256：`6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac`
- simulator SHA-256：`9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5`

## 7. 当前冻结 screen gates

候选必须同时满足：

- 全部审计通过；
- vs bootstrap mean effect ≥`+2%`、cluster CI lower >0、one-sided sign-flip p<0.05、10/10 root directions positive；
- vs exact mean effect ≥`-0.5%`、cluster CI lower >`-1%`；
- vs context mean effect ≥`-1%`、cluster CI lower >`-1%`；
- generator-call reduction vs exact ≥`80%`；
- mean post-bootstrap switches ≤`5.0`。

与 G4/S5 的 head-to-head 只作 descriptive comparison，因为 G4/S5 数据生成了当前 post-hoc hypothesis，不把它追加成事后硬门槛。

## 8. 建议优先提供给研究模型的文件

### Tier A：先上传，体积小且足以理解问题

1. `reports/DEEP_RESEARCH_HANDOFF_2026-07-14.md`（本文件）
2. `results/official_validation_v2_analysis/combined_validation_v2_analysis.md`
3. `results/official_validation_v2_analysis/combined_validation_v2_analysis.json`
4. `results/development_eventreserve/analysis/matrix_v1_combined_analysis.md`
5. `results/development_eventreserve/analysis/matrix_v1_combined_analysis.json`
6. `results/development_dualcap/analysis/matrix_v1_combined_analysis.md`
7. `results/development_dualcap/analysis/matrix_v1_combined_analysis.json`
8. `SOTA_BASELINE_AUDIT_2026-07-14.md`
9. `PAPER_METHOD_EXPERIMENTS_DRAFT.md`
10. `configs/context_dualcap_development_matrix_v1.json`
11. `configs/context_eventreserve_development_matrix_v1.json`
12. `src/dai_lmapf/claim_runner.py`
13. `src/dai_lmapf/publication_policy.py`
14. `scripts/run_claim_aware_budgeted_validation.py`
15. `scripts/analyze_context_eventreserve_development_matrix.py`

### Tier B：协议与证据链核查

1. `ABSOLUTE_WORKLOAD_TAPE_PROTOCOL.md`
2. `CAUSAL_TRIGGER_PROTOCOL.md`
3. `OFFICIAL_BACKBONE_AUDIT.md`
4. `KNOWN_VALIDITY_ISSUES.md`
5. `reports/PROTOCOL_AMENDMENT_VALIDATION_V2.md`
6. `configs/claim_validation_protocol_v2.json`
7. `configs/validation_v2_treatment_freeze_manifest.json`
8. `repro/validation_v2/README.md`
9. `repro/validation_v2/SHA256SUMS`

### Tier C：仅在模型能处理大文件时上传原始数据

- validation-v2 raw：`results/official_validation_v2/{narrow_r020,narrow_r035,regular_r020,regular_r035}.json`，合计约 482 MB。
- G4/S5 raw：`results/development_dualcap/matrix_v1_{narrow_r020,narrow_r035,regular_r020,regular_r035}.json`，合计约 166 MB。

通常无需先上传 Tier C；两个 compact analysis JSON 已包含 root-level effects、strata、审计、统计量和门槛结果。若外部模型提出具体轨迹问题，再按需提供对应 raw artifact。

## 9. 希望外部模型的输出格式

请返回：

1. 一段不超过 300 字的结论：方向继续、转向或停止，以及理由。
2. 对现有结果的独立 validity audit，列出任何错误推断或数据泄漏风险。
3. 最多 3 个下一机制，按信息增益排序，给出伪代码和最小实验矩阵。
4. 对 `context_eventreserve_G5S6` 的先验判断及最可能失败的 gate。
5. 一个 DAI 论文故事线：核心 claim、method novelty、主表、ablation、limitations。
6. 一个 global-SOTA 路线与一个更现实的 Pareto-paper 路线，明确二者所需额外实验成本。
