# Route-Cohort Trigger 实验预注册协议

**版本：** v1.0  
**冻结日期：** 2026-07-14  
**目标 venue：** DAI Research Track  
**状态：** 下一阶段确认性实验协议；当前 MVP 结果仅作开发期诊断，不纳入确认性统计。

## 1. 研究问题与证据边界

本项目的主张不是“检测到分布变化后刷新图会更好”——这一点已由带真实变化信号和 hindsight mask 的 MVP 诊断初步支持——而是：

> 在非平稳 Kiva lifelong MAPF 中，只使用决策时刻之前可观测的运行历史，route-cohort-aware 触发器能在相同 guidance publication 预算下，比验证集选出的最强周期刷新策略获得更高吞吐；或在吞吐非劣的前提下显著减少刷新计算。

确认性实验分为两个可成立的结论路径：

1. **质量路径：** 固定 publication 预算下提高 throughput。
2. **效率路径：** throughput 非劣，同时减少 generator 调用和端到端运行时间。

“SOTA”只能在第 13 节的额外条件全部满足后使用。仅凭当前 3 个 seed、单地图、带 oracle 信息的 MVP，不能声称 deployable improvement、generalization 或 SOTA。

## 2. 当前 MVP artifact 的有效性审计

当前 artifact 可以支持的最强结论是：**publication timing 在该模拟器与当前 guidance 生成器上具有潜在因果杠杆，值得继续研究。** 它们不能作为论文的主实验。

### 2.1 已有的正面证据

- 三个开发 seed 的动态 hindsight shiftmask 均存在优于 bootstrap-only reuse 的 mask，平均约增加 25.33 个完成任务（约 1.71%）。
- 冻结 phase 诊断中 9 个 seed-phase 对有 6 个改善，说明“刷新完全无效”这一反例已被排除。
- artifact 已记录 map、共享库、reset/distribution fingerprint 和 reward-sum invariant；周期 50 的 bucket 语义、oracle shift 触发和 `never = bootstrap-only` 语义已纠正。

### 2.2 残余风险及处置

| 风险 | 对当前结果的影响 | 下一阶段处置 |
|---|---|---|
| `NextRouteFlowGenerator.observe_trace` 可接收真实 distribution update、权重及时间 | 候选 guidance 使用了部署时不可得的 oracle workload state | 确认性方法禁止读取这些字段；只允许历史任务/路径/拥堵统计 |
| shiftmask 由完整 rollout 后验枚举得到 | 存在严重选择偏差，不是在线方法 | 仅保留为 hindsight oracle 上界，不参与主显著性结论 |
| task 在完成后在线生成，方法越快越早消费 RNG/进入不同分布阶段 | 跨方法 realized task exposure 受 treatment 影响 | 必须实现并校验第 8 节的外生 per-agent task tape 后才能进入确认性测试 |
| `post_shift_mean_window_reward` 以 window start 过滤，且混合旧/新 guidance 构建的路径 cohort | 不是严格的 post-shift 因果恢复指标 | 不用于主表；恢复指标按 task release、route-build version 和完成时刻重新定义 |
| 仅 seeds 17–19、单地图、单密度、短 horizon、仅 abrupt Gaussian shift | 方差、拓扑和 workload 泛化未知 | seeds 17–26 永久归为开发集；按第 5 节扩展 benchmark |
| handwritten generator，不是正式训练 checkpoint | 不能与 OnlineGGO/SOTA 直接对比 | 主结果使用冻结的正式 checkpoint；handwritten generator 只作机制消融 |
| phase 结果按 9 个 pair 汇总，但同一 root seed 的 3 个 phase 相关 | 有效样本量被高估 | 统计单位改为 root-seed cluster，不把 window、phase 或 task 当独立样本 |
| 运行耗时受 method order、系统负载和 Python generator 开销影响 | 当前 elapsed-time 不能支持效率结论 | 单独记录 generator CPU/GPU 时间、planner 时间和端到端时间；随机化方法顺序并重复计时 |
| artifact 未冻结完整 source revision、dirty diff、脚本 hash 和 task tape hash | 复现实验身份不完整 | 第 4 节列出的 hash 缺一项即不准进入 test |
| `task_assignment_strategy=roundrobin` 与 Kiva 分支的实际生成逻辑可能不一致 | 元数据名称可能误导 | 以 task tape schema、hash 与消费日志为准，不用该标签证明可比性 |

## 3. 冻结单位与修改规则

确认性实验的最小独立单位是一个 **scenario manifest**：

```text
(map, density, workload family, root seed, horizon, planner budget,
 guidance checkpoint, task tape hash, simulator/build hash)
```

- 同一 manifest 下所有方法共享除 treatment 以外的全部字段。
- 开发集可自由探索，但所有探索和负结果必须保留日志。
- 验证集只允许选择预先列出的 feature、阈值、预算和 baseline 超参数；看到验证结果后不得新增 feature family。
- test manifest 在验证阶段结束前生成、hash、封存；一次性运行全部冻结方法。
- 看过任何 test outcome 后修改算法、阈值、预处理、checkpoint 或评估代码，原 test 即转为开发证据。若必须重启确认性测试，应使用全新的预注册 seed block，并在论文中披露原因，不能只替换不利 seed。
- 基础设施故障可在同一 manifest 上重跑，但须证明故障发生在算法执行前或与方法无关，并保留原失败日志。

## 4. 必须冻结和归档的对象

在 validation 首次运行前归档：

- Git commit、dirty diff、运行脚本 hash、C++ shared library hash、编译器与依赖版本；
- 每张 map 的文件 hash、可通行顶点数和密度到 agent count 的换算结果；
- 每张 map 的正式 guidance checkpoint hash；
- 每个 scenario manifest、完整 task tape hash、独立 RNG stream 配置；
- feature schema、归一化常数、缺失值规则、trigger 参数量和 checkpoint；
- 所有 baseline 的具体版本、命令、timeout 和硬件资源上限；
- 统计脚本 hash，以及 bootstrap RNG seed `20260714`。

要求至少在 3 个开发 manifest 上做 deterministic replay：同一方法重复两次的任务完成数、publication 决策序列、task/route event log 和最终 state fingerprint 必须完全一致；墙钟时间不要求逐位一致。

## 5. 数据划分与 benchmark

### 5.1 Root seeds

| 划分 | Root seeds | 用途 |
|---|---|---|
| Development | 17–26 | feature、模型、消融和故障诊断；17–19 已看过，永久不得进入确认性评估 |
| Validation | 101–110 | 选择一个最终 trigger、周期 baseline 和预算点；不做论文显著性检验 |
| Locked test | 1001–1030 | 一次性确认性统计；以 30 个 root seed cluster 为独立样本 |

每个 root seed 用 SplitMix64 或等价的确定性派生器生成互不复用的 stream：`start_state`、`planner_priority`、`task_tape`、`workload_change`、`method_order`。禁止让某一方法的 RNG 消费次数改变另一 stream。

### 5.2 Map split

- Development：`warehouse_small_narrow_kiva.map`
- Validation：`warehouse_small_kiva.map`
- Locked test：`sortation_small_kiva.map`、`warehouse_60x100_kiva.map`

该划分测试 topology family 和规模泛化。若正式 OnlineGGO checkpoint 必须 map-specific，可使用 map topology 和 development workload 训练每张 map 的 checkpoint，但 checkpoint 必须在 validation/test rollout 前冻结，且不得使用 validation/test task tape 或 outcome。

主张范围仅限上述 Kiva lifelong MAPF 设置；非 Kiva MAPF 的泛化需要单独实验。

### 5.3 Density、时长和 workload

- 密度：`rho ∈ {0.20, 0.35}`，其中 `agent_count = round(rho × |V_free|)`；每张 map 的最终整数在 manifest 中冻结。
- warm-up：200 simulator timesteps，不计入主 throughput，但保留其计算成本。
- 计分 horizon：warm-up 后 2000 timesteps；决策窗口 `D=20`。
- 每个 dynamic workload 有 3 个隐藏 change center，分别由 workload stream 在 `[400,600]`、`[900,1100]`、`[1400,1600]` 内预生成；控制器不可读取其时间。
- workload family：
  1. stationary control；
  2. abrupt Gaussian hotspot shift；
  3. recurrent `A→B→A` hotspot；
  4. gradual drift，在 change center 周围 200 timesteps 内平滑迁移。

主 test 共 `2 maps × 2 densities × 4 workloads × 30 seeds = 480` 个 manifest/方法。任何缩减必须在看 test 前以 protocol amendment 记录；缩减后结论范围同步收窄。

## 6. 提议方法的训练和选择

最终 trigger 必须是 causal policy：在决策时刻 `t` 只根据第 7 节允许的 `≤t` 信息输出 `publish/reuse`。开发集可用 hindsight marginal effect 构造监督标签，但输入特征仍必须是 pre-decision feature。

Validation 上只允许从预先冻结的候选中选一个配置：

- feature families：route-cohort age/mix、历史 throughput/wait/congestion drift、guidance age、历史 publication cost；
- 模型 family：小型 logistic/linear score、深度不超过 3 的 tree，或参数量不超过 10k 的 MLP；
- threshold：开发阶段冻结的有限 grid；
- publication budget：第 9 节的离散预算点。

选择规则为：先剔除违反安全、泄漏或预算的候选；在相同预算内最大化 validation 平均 throughput；差值小于 0.25% 时选择参数更少、publication 更少的候选。Validation 结束后只保留一个主配置，其余仅作开发消融。

## 7. Feature 与信息泄漏边界

### 7.1 允许的信息

在决策时刻 `t` 可使用：

- 静态 map topology、agent count/density；
- 当前 agent 位置和截至 `t` 已公开的当前 goal；
- 截至 `t` 的完成任务、reward、wait、edge/vertex usage、collision-risk proxy；
- execution timestamp `≤t` 的 route-build event、所用 guidance version、path age 和 cohort 构成；
- 截至 `t` 的 planner/generator time、timeout、历史 publication 决策；
- 当前缓存 guidance 的版本/hash、age，以及已消耗的 publication budget。

### 7.2 严禁的信息

部署 trigger、正式 guidance generator 和其预处理均不得访问：

- `recent_distribution_updates`、真实 shift timestamp/index、phase ID、Gaussian center/weights、未来 change schedule；
- generator 内部的真实 Kiva primary/secondary weights 或任何未来 distribution state；
- `t` 之后才 release 的 task、future goal、task-tape 未公开后缀或 tape hash 的可预测编码；
- 当前决策后的 route-build、完成数、reward、planner outcome；
- hindsight mask/oracle action、validation/test label 或其他方法 outcome；
- test aggregate、逐 seed test 曲线或基于 test 做出的 feature/hyperparameter 修改。

从“目前已公开 goal 的经验分布”计算 JS/drift 是允许的，但属于 treatment-dependent runtime state，必须明确命名，不能描述成真实 workload distribution。Oracle-shift 和完整 task-distribution 信息只能用于标有 `diagnostic/oracle` 的非部署曲线。

## 8. 跨方法 task tape：进入确认性实验的最低门槛

当前按任务完成在线抽样的方式不足以进行主结果配对。最低可接受方案如下：

1. 在运行任何方法之前，为每个 manifest 生成**外生、按 agent 预分配**的 task tape。每条记录至少包含：
   `task_id, assigned_agent, release_timestep, origin, goal, workload_source, service_requirement`。
2. 同一 agent 在所有方法中按相同顺序消费相同 task；不得跳过或因完成快慢重新抽样。任务在绝对 simulator timestep release，未完成时进入该 agent 的固定队列。
3. workload change 只影响离线 tape 生成过程；在线 simulator 不再根据某方法的完成时刻抽取 goal。
4. tape 足够长，任何方法在 horizon 内都不能耗尽。若耗尽，整个 manifest 对所有方法重新以更长 tape 生成，不能只补某一方法。
5. 运行前比较完整 tape hash；运行后记录每个 agent 消费的 prefix 长度、task ID、release/start/finish time。方法可消费不同长度的共同前缀，这是 treatment 的结果，不是随机数差异。
6. task tape、start state、planner priority 使用独立 RNG stream。禁止用一个共享 RNG 依次生成所有内容。

若短期内 simulator 不支持 release queue，临时最低实现是：预生成每个 agent 的固定、足够长的有序 goal sequence，禁用在线 Kiva RNG，并把实验明确限制为 **saturated-backlog** setting。该实现可用于 Gate P0/P1，但正式 DAI 主实验应包含绝对 release timestep；否则论文不得声称适用于一般 arrival process。

除 task tape 外，同一 manifest 的 reset fingerprint、distribution/workload manifest fingerprint、start-state hash 和 planner-priority hash 也必须逐方法一致。当前 artifact 只有 reset/distribution fingerprint，仍不满足本节要求。

## 9. Publication 与计算预算

- mandatory bootstrap publication 单独报告，不计入后续预算。
- 若 scored horizon 含 `N=H/D` 个决策窗口，则索引为 `0..N-1`；索引 `0` 是 mandatory bootstrap 且不计预算，因此 post-bootstrap 可行动作数严格为 `K=N-1`。主预算为 `B25 = ceil(0.25 × K)` 次 post-bootstrap publication。对 `H=2000,D=20`，`N=100,K=99,B25=25`，总 generator calls 为 `26`（bootstrap 1 + budgeted 25）。
- exact-even-`B` comparator 在 eligible index `d=1..K` 满足 `floor(dB/K) > floor((d-1)B/K)` 时发布，故严格恰好发布 `B` 次；它不是普通 fixed-period `m` 的别名。
- 预算曲线使用 `{0, 0.10, 0.25, 0.50, 1.00} × K`；主确认性比较固定在 `B25`。
- 超预算动作必须在执行前被 deterministic budget guard 转为 `reuse`，并记录 violation attempt；不得事后删除。
- 相同 guidance backbone 下 publication count 是主要配额；同时报告实际 generator CPU/GPU time、planner time、端到端 wall time、峰值内存和 timeout。
- 计时在同一独占硬件上进行；manifest 内方法顺序由独立 seed 随机化。至少 3 个固定 test seed 额外重复 3 次只用于时间稳定性，不增加统计样本量。
- 若提议方法与 best periodic 的 publication count 相同但 generator time 高出超过 5%，可保留质量比较，但不得声称计算效率。

## 10. 强基线与消融

### 10.1 同 backbone、可配对的主基线

所有方法使用相同 simulator、GPIBT/planner、task tape、正式 checkpoint 和 timeout：

1. uniform/no learned guidance；
2. frozen static/offline GGO guidance；
3. bootstrap-only reuse（原 `never`，论文中不再使用含混名称）；
4. always refresh（period 20，预算曲线诊断，不是 B25 主比较）；
5. fixed periodic `{40, 50, 100, 200}`，以 simulator time bucket 定义而非模运算近似；
6. validation 选出的 **best periodic under B25**，为主 comparator；
7. JS-divergence trigger；
8. throughput/wait-drop trigger；
9. proposed route-cohort trigger；
10. proposed trigger ablations：去掉 cohort、去掉 drift、去掉 cost/budget feature。

observed-shift oracle、per-seed hindsight mask 和 empirical-static candidate 只作为上界/机制诊断，不能计入“击败的 online baseline”。

### 10.2 SOTA 主张所需的公开方法

在接口和任务语义可统一时，至少纳入：

- official OnlineGGO best fixed schedule/checkpoint；
- Guided-PIBT / Traffic Flow Optimization；
- WPPL 或 EPIBT；
- RHCR-PBS/ECBS；
- PIBT2；
- RL-RH-PP（若有可复现实现且许可、硬件设置可对齐）。

公开方法必须使用同一 map、agent count、task tape、horizon、timeout 和硬件预算。若某方法不能消费相同 release tape 或求解语义不同，放入单独的“non-aligned reference”表，不能用其结果支持配对显著性或 SOTA。

至少在第二个冻结 guidance backbone 上复现触发器相对于该 backbone 最强周期策略的方向性收益，以排除只对 handwritten/某一 checkpoint 过拟合。

## 11. 指标

### 11.1 唯一主指标

```text
throughput = warm-up 后完成的非零 service task 数 / 实际计分 timestep
```

主 paired effect 对每个 test root seed `i` 先在所有预注册 scenario cell 上等权平均：

```text
d_i = mean_cell((throughput_proposed - throughput_best_periodic)
                / throughput_best_periodic)
```

每个 map/density/workload cell 等权，不能让大地图或任务更多的 cell 获得更高权重。Baseline throughput 必须大于 0，否则该 manifest 按失败规则处理，不临时修改分母。

### 11.2 关键次要指标

- absolute task-count difference；
- dynamic regret / completion AUC；
- change 后 100、200 timesteps 的 recovery AUC，以及恢复到 pre-change throughput 95% 的时间；
- publication 次数、generator time、planner time、端到端 wall time；
- p50/p95 task service time、wait ratio、timeout rate；
- 按 route-build guidance version 划分的 stale-route exposure 和 cohort completion；
- budget violation attempt、collision、vertex/edge-swap violation 和 invalid goal 数。

恢复指标按 manifest 聚类统计，并同时以 task release cohort 与 route-build guidance version 报告。旧的 `post_shift_mean_window_reward` 不进入主表。

## 12. 统计方法与失败处理

- 独立统计单位为 30 个 locked test root-seed cluster；同 seed 下所有 map/density/workload 一起重采样。
- 主效应报告 30 个 `d_i` 的均值、中位数、win rate 和全部 seed 点。
- 95% CI：paired cluster bootstrap，10,000 次，以 RNG seed `20260714` 重采样 root seeds。
- 主假设 `H1: mean(d_i) > 0` 使用单侧 paired randomization/sign-flip test，100,000 次；显著性水平 `α=0.05`。
- 唯一主比较是 proposed 对 validation-selected best periodic under B25，因此不做主比较多重校正。
- 对 bootstrap-only、JS trigger、throughput-drop trigger 的确认性次比较，以及多个公开 competitor 的比较，分别在各自 family 内使用 Holm correction。其他消融和 oracle 结果标为 exploratory。
- window、phase、task、agent 不能当作 iid 样本；phase/recovery CI 必须按 root seed cluster bootstrap。
- 同时报告绝对差、相对差、CI、校正后 p-value 和 effect distribution，不只报告“胜率”。

失败规则：

- collision、edge swap 或非法目标是 safety failure；主方法出现任何此类 failure，Gate P0 直接失败。
- algorithm/planner timeout 是方法 outcome，保留 timeout 前完成数，剩余 horizon 计 0 新完成；不得删除 manifest 或换 seed。
- 与算法无关的基础设施 crash 允许同 manifest 重跑；若修复改变二进制、逻辑或随机数流，则所有受影响方法/manifest 必须一起重跑并更新 freeze 记录。
- 不允许 complete-case analysis，不允许因 baseline 表现异常而事后排除 cell。

## 13. Go / No-Go 阈值

### Gate P0：正确性和可比性

以下条件全部满足才可进入 validation：

- 所有开发 replay 无 collision、edge swap、invalid goal；
- 同 manifest 各方法的 task tape、start state、workload manifest、planner-priority fingerprint 一致；
- reward/task conservation invariant 通过；
- deterministic replay 完全一致；
- causal trigger 与正式 generator 的 forbidden-field access test 通过；
- build、source、checkpoint、manifest 和统计脚本均有 hash。

任一失败即 **No-Go**，先修基础设施，不解释性能。

### Gate P1：Validation freeze

进入 locked test 至少满足一个条件：

- **质量候选：** 相对 best periodic under B25 的 validation 平均 throughput ≥ `+1.0%`；或
- **效率候选：** validation 平均 throughput ≥ `-0.5%`，且 generator time 或 publication count 至少减少 `30%`。

两条路径都要求：零 safety failure、零实际超预算、任一 validation scenario cell 不劣于 best periodic 超过 `5%`。不满足则 **No-Go**，继续留在开发阶段，不能打开 test。

### Gate P2：Locked test 论文结论

**质量 GO** 必须同时满足：

- test 平均相对 throughput `mean(d_i) ≥ +2.0%`；
- paired 95% CI 下界 `> 0`，主单侧检验 `p < 0.05`；
- 两张 test map 的 cell-mean 均为正，4 个 workload family 中至少 3 个为正；
- stationary control 平均退化不超过 `1.0%`；
- ≥60% 的 root-seed clusters 上 `d_i > 0`；
- safety failure 为 0，budget violation attempt 占决策不超过 5%，实际超预算为 0。

**效率 GO** 必须同时满足：

- test 平均相对 throughput ≥ `-0.5%`，paired 95% CI 下界 `> -1.0%`；
- 相对 best periodic，generator time 或 publication count 至少减少 `40%`；
- 端到端 wall time 至少减少 `20%`；
- 两张 test map 都满足非劣界，且 safety/预算条件与质量路径相同。

若两条路径都不满足，结果为 **No-Go/negative result**；不得用 hindsight oracle 的改善替代在线结果。

### “SOTA”标签的额外门槛

只有同时满足以下条件，摘要和标题才可使用 SOTA：

- 通过质量 GO，而不只是效率 GO；
- 在完全对齐的公开方法中，对最强 deployable competitor 的相对 throughput ≥ `+2%`，Holm 校正后的 95% CI 下界 `>0`；
- 在 throughput–wall-time Pareto 图上非支配，且相对既有方法集合的预注册 hypervolume 至少提高 `5%`；
- 两张 test map 均保持方向性收益，并在第二个冻结 guidance backbone 上复现；
- 所有公开方法、task tape、manifest、日志和统计脚本可复现。

若公开 baseline 无法语义对齐，论文最多声称“优于强周期/事件触发 baseline”，不能声称全领域 SOTA。

## 14. 最低报告清单

论文和 artifact 必须同时提供：

- 完整 protocol 与任何带时间戳的 amendment；
- 所有 manifest/hash、seed 列表、task tape generator 与 tape 消费日志；
- 每个 seed/cell/method 的原始指标，而非仅均值；
- 全部方法的 publication timeline、guidance version/route cohort trace；
- 配对 effect 分布、bootstrap CI、randomization test 和 Holm 表；
- throughput–publication、throughput–generator-time、throughput–wall-time 三张 Pareto 图；
- 失败、timeout、预算 violation、排除和重跑的完整日志；
- oracle/hindsight、开发、validation、locked test 结果在表格中清晰分区。

本协议生效后，seeds 17–26 只用于开发，101–110 只用于验证，1001–1030 只用于一次性 locked test。当前 MVP artifact 应在论文中标注为 **mechanism diagnostic / pilot study**，不与 locked test 合并计算置信区间或 p-value。
