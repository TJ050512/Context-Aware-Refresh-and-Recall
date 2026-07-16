# Same-Call A2 确认性实验决策备忘录

日期：2026-07-14  
用途：冻结实验后的论文决策与写作边界  
证据范围：同一 OnlineGGO backbone、四个注册场景、三类注册 workload；不代表全局 LMAPF SOTA

## 1. 执行结论

### 确认性结论

A2 完整性审计通过，但机械分层结果为：

> **Tier C — `TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER`**

这表示原先注册的“当前 context-memory 方法以很少生成调用实现相对
`exact_even_B25` 的近乎无损性能，并以历史重激活带来额外价值”这一整套主张没有通过。
失败原因不是实验损坏：960 个必需运行全部完成，零失败、零重试删除、零选择性删除，
而是关键的 1% 非劣性检验未通过，且历史重激活没有显示正的平均吞吐贡献。

### 决策建议

1. **停止按原来的“context memory 全面成功/近乎无损”叙事写稿。** A2 已经给出最终否定结论，
   不能通过挑选场景、追加少量 root 或改阈值来补救。
2. **可以继续写一篇显著收窄、诚实重构的 DAI 稿件**：把单点贡献改为
   “同 backbone 下 guidance refresh 策略的计算调用—吞吐 Pareto 研究，以及一个低调用的
   context-memory operating point”。这是一项资源效率与评估贡献，不是非劣性或 SOTA 贡献。
3. 若仍要保留“近乎无损”“历史重激活有效”或实际运行时节省等强主张，**必须另立新协议、
   新方法版本和全新未触碰 roots 做新的确认性实验**；当前 A2 不支持这些主张。

## 2. 证据身份与完整性

### 确认性结果

- 最终分析 JSON：`reports/same_call_confirmation_a2_analysis.json`
  - SHA-256：`9257a16f8fadb2135bcc434cb731abda9d2ba452b85287bff045e667ae37a71e`
- 最终分析 Markdown：`reports/same_call_confirmation_a2_analysis.md`
  - SHA-256：`2358e8a3c51d7b14b6806d85eb72a9e172876641973143eac7f219ed6c0c495e`
- 最终 A2 config：`configs/same_call_confirmation_a2.json`
  - SHA-256：`e0763c409c900bbc21e9b69fff5e978261a89cba8ad883d16ef705d012c9d96f`
- A2 implementation freeze：`configs/same_call_implementation_freeze_a2.json`
  - SHA-256：`7ab9603a526c335d376a42c789072ddca1e23d83e38994fa9b6c732e65dcb97a`
- A2 preflight：`reports/same_call_preflight_a2.json`
  - SHA-256：`a65a63b6d741dcfd15f21193ffa20ee0fc847ce3b08ff9524a5885665ff15955`
- 分析器修订：`dai.same-call-confirmation-analyzer/a2-process-identity`
- 证据范围由冻结分析器明确限定为：
  `fresh post-validation same-backbone confirmation; never global LMAPF SOTA`。

实验设计为 8 个方法 × 10 个独立 root × 4 个场景 × 3 个 workload，共 **960 runs**。
统计独立单位是 root seed；每个方法每个 root 等权汇总 12 个 cell，每个方法共有 120 个配对 cell。
置信区间使用 10,000 次 whole-root percentile bootstrap，固定 bootstrap seed `20260715`；
六个优效比较使用 exact root sign-flip，并以 Holm step-down 控制 familywise alpha 0.05。

完整性审计结果：

| 审计项 | 结果 |
|---|---:|
| 完整矩阵 | 960/960 |
| started / completed attempts | 960 / 960 |
| 唯一 process instances | 960 |
| 唯一 run UUID | 960 |
| 方法失败或重试事件 | 0 |
| 未完成 attempt | 0 |
| planner timeout | 0 |
| timeout deletion | 0 |
| selective cell deletion | 0 |
| 安全、不变量、预算与 schedule | 全部通过 |
| 配对外生输入 | 全部一致 |
| 源码、config、preflight 哈希 | 全部通过 |

A1 结果没有进入估计、排序或解释；本备忘录只使用最终 A2 分析文件中的确认性数字。

## 3. 核心性能结果

### 3.1 六个冻结优效比较

下表中的 Δ 均为 `context_memory_B25 − comparator`；正值表示 context-memory 完成更多任务。

| Comparator | 平均任务差 | 平均 Δ | 95% root CI | Root W/T/L | raw p | Holm p | 确认性判断 |
|---|---:|---:|---:|---:|---:|---:|---|
| `bootstrap_only` | +154.30 | +3.72% | [+3.04%, +4.44%] | 10/0/0 | 0.0009766 | 0.005859 | 通过 |
| `exact_even_G4` | +86.20 | +2.04% | [+1.40%, +2.67%] | 10/0/0 | 0.0009766 | 0.005859 | 通过 |
| `exact_even_G5` | +8.65 | +0.17% | [-0.33%, +0.61%] | 7/0/3 | 0.2588 | 0.5176 | 未通过 |
| `random_G5` | +54.43 | +1.22% | [+0.14%, +2.52%] | 6/0/4 | 0.03906 | 0.1172 | Holm 后未通过 |
| `js_cap_G5` | +142.71 | +3.11% | [+2.32%, +3.93%] | 10/0/0 | 0.0009766 | 0.005859 | 通过 |
| `context_no_reactivation_B25` | -5.78 | -0.11% | [-0.48%, +0.21%] | 5/0/5 | 0.7080 | 0.7080 | 未通过，点估计为负 |

可确认的优效对象只有三个：`bootstrap_only`、`exact_even_G4` 和 `js_cap_G5`。
不能把 raw p=0.03906 的 `random_G5` 写成家族校正后显著；也不能声称优于
`exact_even_G5` 或 `context_no_reactivation_B25`。

### 3.2 与高调用 `exact_even_B25` 的注册非劣性检验

### 确认性结果

| 指标 | 数值 | 注册门槛 | 结果 |
|---|---:|---:|---|
| context-memory 平均 tasks | 4571.325 | — | — |
| exact B25 平均 tasks | 4598.917 | — | — |
| 平均绝对差 | -27.592 tasks | — | 描述性 |
| 平均相对差 | **-0.4009%** | 至少 -0.5% | 通过该子门槛 |
| 95% root CI | **[-1.0834%, +0.2584%]** | 下界严格高于 -1% | 失败 |
| shifted one-sided exact p | **0.06836** | <0.05 | 失败 |
| Root W/T/L | 3/0/7 | — | 描述性 |
| 最终 1% 非劣性 | — | 三项均须通过 | **FAIL** |

观察到的平均差只有 -0.40%，但区间仍允许超过 1% 的退化，并且预注册的 shifted exact
检验没有达到 0.05。因此，只能写“观察到的平均差为 -0.40%，非劣性未建立”，不能写
“性能保持不变”“近乎无损”“1% 内非劣”或“与 exact B25 等效”。

该差异在 narrow map 上点估计为 +0.43%，在 regular map 上为 -1.23%；四个场景中
`regular_r035` 为 -1.55%。这些是注册分解结果，但不能用有利的 narrow 子组替代总体失败结论。

### 3.3 调用量和 Pareto 点

### 确认性结果

| Method | Mean tasks | Calls mean / median / P90 / max | Calls ≤5 / ≤6 | Post generations mean | Switches mean | Reactivations mean |
|---|---:|---:|---:|---:|---:|---:|
| `bootstrap_only` | 4417.025 | 1.00 / 1 / 1 / 1 | 100.0% / 100.0% | 0.00 | 0.00 | 0.00 |
| `exact_even_G4` | 4485.125 | 5.00 / 5 / 5 / 5 | 100.0% / 100.0% | 4.00 | 4.00 | 0.00 |
| `exact_even_G5` | 4562.675 | 6.00 / 6 / 6 / 6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `random_G5` | 4516.892 | 6.00 / 6 / 6 / 6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `js_cap_G5` | 4428.617 | 6.00 / 6 / 6 / 6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `context_no_reactivation_B25` | 4577.100 | 6.98 / 6.5 / 10 / 13 | 36.7% / 50.0% | 5.98 | 5.98 | 0.00 |
| `context_memory_B25` | 4571.325 | **5.47 / 5 / 8 / 12** | **60.8% / 78.3%** | 4.47 | 6.12 | 1.65 |
| `exact_even_B25` | 4598.917 | 26.00 / 26 / 26 / 26 | 0.0% / 0.0% | 25.00 | 25.00 | 0.00 |

相对 `exact_even_B25`，context-memory 的平均 generator calls 从 26 降至 5.4667，
点估计减少 **78.97%**。冻结的二维点 Pareto frontier 为：

- `bootstrap_only`
- `exact_even_G4`
- `context_no_reactivation_B25`
- `context_memory_B25`
- `exact_even_B25`

`context_memory_B25` 在“mean tasks、mean calls”这两个点指标上不被其他方法支配。
这是描述性的 operating-point/Pareto 结论，不等价于吞吐非劣，也不证明 wall-clock、GPU 时间、
能耗或端到端成本按 78.97% 同比例下降。

### 3.4 历史重激活的实际证据

### 确认性结果

相对同一控制器但禁用历史重激活的 `context_no_reactivation_B25`：

- 平均 tasks：4571.325 vs 4577.100；
- 平均差：-5.775 tasks，-0.1135%；
- 95% root CI：[-0.4801%, +0.2121%]；
- Holm p=0.7080，Root W/T/L=5/0/5；
- 平均 calls：5.4667 vs 6.9833；
- context-memory 平均发生 1.65 次 reactivation。

因此，数据支持“历史重激活降低了生成调用点估计”这一资源行为描述，但**不支持历史重激活提高
吞吐**；吞吐点估计反而略低。不能把 calls 的下降改写成历史重激活的性能增益。

### 3.5 跨地图和 workload 的边界

### 确认性结果

相对 `bootstrap_only`，context-memory 在两类地图及三个 workload 的平均 Δ 都为正：

- narrow +3.52%，regular +3.91%；
- stationary +1.77%，abrupt +4.28%，recurrent +5.11%。

但相对更关键的 `exact_even_G5`：

- narrow +0.93%，regular -0.59%；
- stationary **-1.32%**，abrupt +0.32%，recurrent +1.51%。

所以可以报告其相对 bootstrap 的跨注册环境一致性，不能泛化为“对所有强 sparse baseline、所有
地图和 workload 都稳定更好”。特别是 stationary 相对 exact G5 的 -1.32% 触发了 Tier A
附加门槛失败。

## 4. 为什么机械判定是 Tier C

### 确认性结果

Tier B 的 11 个门槛中，10 个通过：审计、相对 bootstrap 的均值/CI/Holm、平均 calls≤6、
相对 exact B25 调用减少≥75%、Pareto 不被点支配、两类地图和三个 workload 上相对 bootstrap
均为正、零选择性删除均通过。唯一失败项是：

> `exact_b25_1pct_noninferiority = false`

Tier B 要求所有门槛同时成立，因此该单项失败已经机械地导致 Tier B 不成立，最终进入 Tier C。

Tier A 同时还失败五项：

1. 六个优效比较并非全部 Holm p<0.05；
2. 六个优效比较并非全部 CI 下界>0；
3. `historical_recall_mean_positive=false`；
4. `g5_positive_both_maps=false`；
5. `g5_stationary_degradation_no_worse_than_1pct=false`。

这不是“差一点所以可按 Tier B 写”的主观判断。Tier 是预注册机械规则；p=0.06836 和 CI 下界
-1.0834% 只能如实报告为失败。

## 5. 仍可投稿的单点贡献

### 决策建议，不是确认性判定

最可辩护的单点贡献是：

> **在相同 OnlineGGO backbone 和严格配对、fresh-root 的确认性评估下，context-aware memory/reuse
> 将 guidance generation 的平均调用从高频 B25 的 26 次降至 5.47 次，形成一个不被点支配的
> 低调用 operating point；同时实验明确量化了其吞吐不确定性和历史重激活的边界。**

支持这个叙事的确认性事实包括：

- 相对 exact B25 的 calls 点估计减少 78.97%；
- 平均 calls 5.47，median 5，P90 8；60.8% 的运行不超过 5 次，78.3% 不超过 6 次；
- mean tasks–mean calls 二维点位于冻结 Pareto frontier；
- 相对 bootstrap、exact G4、JS-cap G5 的优效经 Holm 校正后成立；
- 相对 exact B25 的观察平均吞吐差为 -0.40%，但必须同时披露 1% 非劣性失败；
- 历史重激活的价值主要表现为少调用，而不是已证实的吞吐提升。

适合的论文定位是“resource-aware guidance refresh / empirical systems evaluation / rigorously bounded
negative and trade-off result”。它不是原注册协议意义上的 Tier A/B context-memory 成功论文。
仅靠这一点投稿 DAI Research Track 是可以尝试的，但风险明显高于拥有已确认非劣性或跨 backbone
结果的版本。论文价值应来自清楚的问题定义、严格的同 backbone 因果对照、可复现实验资产和诚实的
trade-off 边界，而不是把弱比较包装成全面 SOTA。

## 6. Claim 白名单与黑名单

### 6.1 允许的 claim（必须保留范围和限定词）

1. “在冻结的 same-backbone、4 场景 × 3 workload × 10 roots 设置中，完整 960-run 审计通过。”
2. “Context-memory 相对 bootstrap、exact G4、JS-cap G5 分别提高 3.72%、2.04%、3.11%，
   其 root CI 下界为正且六比较 Holm 校正后 p=0.005859。”
3. “其平均 generator calls 为 5.47；相对 exact B25 的 26 次，描述性点估计减少 78.97%。”
4. “Context-memory 位于预定义 mean-tasks/mean-calls Pareto frontier，且未被点支配。”
5. “相对 exact B25 的观察平均吞吐差为 -0.40%，但 1% 非劣性未建立
   （CI [-1.08%, +0.26%]，shifted p=0.06836）。”
6. “相对 no-reactivation 版本，历史重激活没有显示正的平均吞吐贡献；其可见作用是降低生成调用点估计。”
7. “全部结论只适用于注册的同 backbone 设置；本实验不构成 global LMAPF SOTA 证据。”

### 6.2 禁止的 claim

1. 禁止写 “Tier A/B”“GO”“确认成功”“全面 SOTA”或“达到/刷新 LMAPF SOTA”。
2. 禁止写 “与 exact B25 非劣/等效/性能保持不变/近乎无损/退化小于 1%”。
3. 禁止写 “优于全部 baseline”；对 exact G5 未显著，对 random G5 在 Holm 后未显著，
   对 no-reactivation 点估计为负。
4. 禁止写 “historical recall/reactivation 提高吞吐”或“context memory 本身已被消融证明有效”。
5. 禁止把 78.97% calls reduction 说成 78.97% wall-clock、GPU time、能耗或货币成本下降。
   当前没有这种测量，而且注册规则对 Tier C 禁止进入原 timing-only 阶段。
6. 禁止把有利的 narrow、recurrent 或单场景结果提升为新的确认性主结果；总体检验优先。
7. 禁止报告未校正的 random G5 p=0.03906 为多重比较后的显著结果。
8. 禁止使用 A1 outcomes，或把 A1 与 A2 pooled、比较、替代或用于解释 A2。
9. 禁止在看过 A2 后修改当前方法/阈值，再把 A2 roots 当成“新测试集”重跑。
10. 禁止把调用次数这一代理指标直接称为实际推理开销、延迟或硬件效率。

## 7. 是否需要后续新协议实验

### 确认性结论

- A2 本身已经完成；不能选择性补跑或追加少量 root 来改变其 Tier。
- 原协议规定 Tier C 不进入原先的 timing-only 阶段，因此当前 A2 不能据此新增 confirmatory runtime claim。
- A2 已经构成最终、完整的负面/边界与 Pareto 证据，不需要为了“让已有数字合法”而重跑。

### 决策建议

按论文目标分两种情况：

**A. 明天立即写显著收窄的 trade-off/evaluation 稿件：**

- 不强制新增实验；先用 A2 写出完整、诚实的 Methods、Results、Limitations。
- 但投稿竞争力有限。若时间允许，最有价值的扩展是另立协议测真实 wall-clock/CPU cost，并扩大地图或
  backbone 覆盖；这些扩展不能伪装成当前 A2 的预注册结果。

**B. 仍想写强 context-memory algorithm paper：**

- 必须先在明确标记为 development 的数据上修改方法，使重激活确实带来吞吐或更稳健的计算收益；
- 冻结新方法、estimand、非劣 margin、样本量和停止规则；
- 派生一组全新、未触碰 roots，执行完整新确认矩阵；
- A2 已经被看过，若用它指导设计，它只能作为新方法的 development evidence，不能继续充当独立确认集；
- 不能因为本次 p=0.06836 而临时追加 roots 后与 A2 opportunistically pooling。任何 replication/扩样
  必须在新协议中事先确定并单独披露。

建议优先级：先完成 A2 论文骨架；若写完后发现主张仍不足，再决定是否投入新协议。不要今晚继续盲目
跑同一方法的更多 seeds。

## 8. 明天写作清单

### 必须完成

- [ ] 锁定以上五个核心文件及 SHA-256；不再修改、覆盖或重新分析 A2。
- [ ] 在标题、摘要第一版中将主题改成 **resource-aware guidance refresh / compute–throughput trade-off**，
      删除 SOTA、near-lossless、non-inferior 等措辞。
- [ ] Introduction 明确一个问题：昂贵 guidance generation 能否通过 context-aware reuse 降低调用，
      以及这种节省会付出什么吞吐代价。
- [ ] Contributions 只保留 2–3 点：控制策略/operating point、严格 same-backbone 确认协议、
      透明的 trade-off/负面边界；不要写“全面优于”。
- [ ] Methods 写清 8 个方法、4 场景、3 workload、10 roots、960 runs、fresh process、配对外生输入、
      root-cluster bootstrap、exact sign-flip、Holm 校正和 1% 非劣性规则。
- [ ] 单独解释 A1 PID recycling 只属于 execution audit，A1 在 effect analysis 前废弃，A2 使用新 roots；
      不展示或讨论 A1 outcomes。
- [ ] Results 表 1：完整性审计；表 2：8 方法 mean tasks/calls；表 3：六个冻结优效比较；
      表 4：exact B25 非劣性失败。
- [ ] 画一张 mean calls–mean tasks Pareto 图；对 `context_memory_B25`、`exact_even_B25`、
      `context_no_reactivation_B25` 加标签。图注注明是点估计 frontier，不是统计非劣证明。
- [ ] 消融小节明确写：reactivation 平均 calls 下降，但 tasks 为 -0.11%，CI 跨零，Holm p=0.708。
- [ ] Limitations 明确：same backbone、有限地图/workload、只有 10 个独立 root、call 是成本代理、
      未做 Tier-C timing、非劣性失败、不可声称 global SOTA。
- [ ] Abstract 和 Conclusion 同时包含 exact B25 的 -0.40%、CI 和非劣失败，避免只报有利 calls。
- [ ] 在最终投稿前逐句按本备忘录的 claim 白名单/黑名单审阅。

### 可选但有价值

- [ ] 增加一张按 map/workload 的 secondary breakdown 图，但标为注册分解/描述性结果，不能改变总体结论。
- [ ] 在 Related Work 中把贡献放到 adaptive computation、dynamic guidance refresh、multi-agent systems
      evaluation，而不是无依据地与全局 MAPF SOTA 排名。
- [ ] 起草一个独立的后续协议草案，专门测 wall-clock 和跨 backbone 泛化；在决定执行前不打开新 roots。
- [ ] 准备 reproducibility appendix：config、protocol、source hash、preflight、process-instance/UUID gate、
      统计代码版本和完整审计计数。

## 9. 一句话对外口径

### 建议措辞

> 在严格的同 backbone 确认性评估中，context-aware reuse 将平均 guidance-generation 调用从 26 次
> 降至 5.47 次并形成一个 Pareto operating point；其相对高调用基线的观察平均吞吐差为 -0.40%，
> 但预注册的 1% 非劣性检验未通过，因此我们将结果定位为计算—吞吐权衡，而非无损替代或全局 SOTA。
