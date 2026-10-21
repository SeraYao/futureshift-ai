# FutureShift AI — 数据来源验证清单

预赛已确定采用 O*NET 31.0 官方可下载 CSV 作为职业技能基准、GitHub REST Repository Search API 作为动态开源技术活动信号。方案已确定不代表已接入：本轮已下载必要官方文件完成下述核验，未接入评分代码，也未调用 GitHub API；查询主题及运行环境仍需验证。官方需求依据为本仓库 `reference/domain-1-brief.pdf`；该文件已阅读，但其中的背景统计尚未独立核验，不直接用于评分。

| Source | Purpose | Data Type | Access Method | Reliability | Update Frequency | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 职业技能：O*NET 31.0 官方 CSV | 少量真实职业及技能基准 | 职业标识、技能及选定要求字段 | 官方 31.0 CSV 已下载检查；见下方实际文件与字段 | 主要反映美国职业体系，不能声称代表马来西亚就业预测 | 固定 31.0；官方发布月份为 2026-08 | 文件、字段、量表及职业存在性已核实；转换校准待验证 |
| 动态 AI 趋势：GitHub REST Repository Search API | 比较 AI 技能主题的新建公开仓库活动 | 两个连续 90 天窗口的返回计数与查询元数据 | Repository Search API；匿名搜索按最多 10 次/分钟设计，使用缓存 | 仅表示开源技术活动动量，不代表职位需求、工资或就业增长 | 按缓存策略刷新；查询主题与缓存有效期待验证 | 客户端及显式 Refresh 已接入；三职业映射为原型假设，尚待验证；Replit 连通性待验证 |
| 备用研究趋势：arXiv API | 后续或备用研究活动信号 | 研究元数据、日期及主题 | 传统接口按最多每 3 秒一次请求设计 | 研究活动不等于就业增长；质量及技能映射待验证 | 按需；不进入预赛核心依赖 | 备用方案；未接入 |
| 学习资源：高校开放课程、提供方官方课程目录、HRD Corp 项目目录候选 | 为缺口匹配免费或低价资源 | 课程名、技能、先修、时长、费用及资格条件 | 待验证：官方页面/可用目录、引用和保存条件 | 待验证：链接、费用、课程有效性及可报名条件 | 待验证：提供方更新节奏；保存核验日期 | 待验证 |
| SDG 定义：联合国官方 SDG 目标与 targets | 定义 17 个目标并支持贡献解释 | SDG 编号、target、官方描述 | 待验证：官方页面/文件和复用许可 | 待验证：版本及具体 target 对应；职业技能映射需人工审查 | 待验证：版本日期、变更及复查周期 | 待验证 |

## 已确定的预赛采集与记录方案

### O*NET 31.0 职业技能基准

仅选取预赛需要的少量真实职业及其技能字段，不导入无关全量数据。每份选取结果保存数据库版本 31.0、官方发布日期、原始来源链接、文件/字段标识、获取日期及许可归属和署名要求。本轮已核对实际 CSV、字段、量表、许可及发布月份，详见核验记录；具体发布日期的日未证实，不填入推测值。使用稳定职业/技能 ID，保留人工筛选与映射依据。

O*NET 主要反映美国职业体系；它提供职业技能基准，不是马来西亚岗位需求或就业预测。若映射到本地语境，应说明适用边界。

### GitHub 动态趋势快照

对预先定义并附说明的 AI 技能主题，使用相同查询规则比较最近 90 天与此前 90 天新建的公开仓库数量。主题需记录检索词、纳入理由及其到 O*NET 技能/职业的映射依据；不得在看到结果后临时换词以制造增长。

每次保存：查询词、查询时间（UTC）、两个时间窗的起止边界、各窗口返回计数、完整来源 URL、缓存写入时间，以及 API 返回是否完整的状态。以 UTC 日期和两个相邻、不重叠的完整 90 天窗口构造查询，保存实际边界；同一主题两窗口除创建日期外使用相同过滤条件。计数转换已确定采用平滑参数 20 的截断 log2 公式，职业趋势为主题加权平均；具体主题映射和聚合权重仍待验证。

匿名搜索调用按每分钟最多 10 次设计；每个主题至少有两次窗口查询，须共享请求预算、复用缓存并避免频繁刷新。处理服务端限流响应；不能以本地预算替代服务端限制。API 失败时保留最后一次成功快照，界面明确显示 `cached`、原查询时间和缓存时间，并显示失败状态；无成功快照则标记不可用。失败不得覆盖成功快照时间，也不能模拟实时刷新。

指标仅表示开源技术活动动量，不等同于职位需求、工资或就业增长。仓库数量受查询覆盖、重复/低质量仓库、平台人群及可见性变化影响；不能推断马来西亚市场需求。主题到职业技能的映射和信号归一化需人工审查。

### 已确认并启用的三职业 GitHub topic 映射

记录与官方文档访问日期：**2026-10-21**。以下范围经用户确认，状态统一为 **“原型假设，尚待验证”**；确认只授权实现这些查询，不代表主题覆盖、职业任务关联或预测有效性已经验证。尚未进行真实 API 抓取；实际数据访问时间以每个查询的 fetched_at 为准。

| O*NET code | Exact occupation title | GitHub topic（职业内权重） | 选择理由（项目假设） | 状态 |
| --- | --- | --- | --- | --- |
| 15-2051.00 | Data Scientists | machine-learning（0.5）、data-science（0.5） | 用机器学习和数据科学主题观察与建模、分析实践相关的开源活动；不是该职业全部任务或岗位需求的代表样本 | 原型假设，尚待验证 |
| 15-2031.00 | Operations Research Analysts | operations-research（0.5）、optimization（0.5） | 用运筹和优化主题观察与定量决策方法相关的开源活动；不能据此推断运筹职位增长 | 原型假设，尚待验证 |
| 15-1252.00 | Software Developers | code-generation（0.5）、software-testing（0.5） | 用代码生成和软件测试主题观察部分开发工具活动；只覆盖软件工作的一部分，也不能等同于全部 AI 活动 | 原型假设，尚待验证 |

查询与执行契约：

- 每个主题独立精确查询 `topic:<slug> visibility:public fork:false created:<start>..<inclusive_end>`，通过 GitHub REST Repository Search API 的 `q` 参数编码；不自动扩词、不新增其他职业映射。其余七个职业不查询、不借用这三个职业的结果。
- UTC 参考日 D 不纳入尚未完整的一天：最近窗口 `[D−90, D)`，此前窗口 `[D−180, D−90)`。GitHub 创建日期过滤使用包含端点的日期区间，因此查询结束日期为 end_exclusive 减一天。每个结果保留完整查询、来源 URL、两个窗口边界、total_count、incomplete_results、HTTP 状态及抓取时间。
- 每个职业只有两个主题，每次成功且不命中缓存的显式 **Refresh** 发出 **4 次搜索请求**（两个主题 × 两个窗口），不会刷新其他职业。缓存仍有效时不请求；任何请求失败或限流时提前停止，不强行凑满四次，也不自动重试。
- 职业内两个 T_k 等权聚合，沿用现有趋势公式及平滑参数 20。主题可能重叠，分数是主题分数平均，不把两个主题计数求和称为不同仓库总数。
- 匿名搜索按每滚动分钟最多 10 次设计，进程内所有页面会话共享预算；同时遵守服务端 Retry-After / X-RateLimit-Reset。点击后四次请求需全部成功且 incomplete_results=false，才原子替换该职业成功快照；失败不能变为 0，也不能拼接新旧窗口。
- 成功快照缓存 15 分钟；UTC 日期变化也使窗口过期。失败时显示错误和最后完整成功缓存的原始日期、cached/expired 状态；没有缓存则明确不可用。缓存保存在本地 data/cache/github_trends.json，已精确忽略，不写入 demo JSON。
- 页面明确标记映射状态及解释边界：**GitHub 仓库活动只是开源活动代理指标，不等于招聘数量、工资或就业增长预测。** 平台用户、主题标注覆盖、检索范围和仓库质量均会造成偏差；返回计数是 API 报告值，不是完整活动普查。
- 趋势证据只在 O*NET data audit 中展示；O*NET 质量阻断仍保留，即使 T 可算也不生成个人适配总分、情景总分或职业排名。Synthetic simulation 继续仅使用三个 demo JSON。

官方语法与限制依据：[Repository Search API](https://docs.github.com/en/rest/search/search#search-repositories)、[repository topic 搜索](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories#search-by-topic)、[REST API 限流](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。文档访问不等于已经获取实际仓库计数；真实连通性、样本质量和职业关联仍待验证。

### arXiv 备用

arXiv API 仅作为后续或备用研究趋势信号；传统接口按最多每 3 秒一次请求限制设计，使用缓存。预赛核心流程不依赖 arXiv，未接入时不影响 O*NET + GitHub 链路。

## 上线前验证门槛

- 访问与许可：确认官方来源链接、文件/API、授权、限流、缓存、引用及再分发条件；公开可读不等于自由使用。
- 覆盖与日期：记录地域、分类粒度、原始发布日期/数据时期、获取日期及版本；未知日期明确标记，不以获取日期替代发布日期。
- 映射：保存职业、技能、GitHub 主题、课程及 SDG 的 ID 和关联依据、歧义与人工审查状态。
- 可复算性：快照保留原始计数、窗口、查询和变换规则；更新前后比较固定其他输入版本。历史回放和合成测试必须分别标记。
- 事实边界：不将新闻、研究或仓库活动热度直接解释为岗位增长。没有市场数据时，就业需求结论标记缺少证据；推荐只引用已核验的真实职业、技能、课程及统计。

## 已确定的原型评分规则（有效性待验证）

- 技能/知识沿用 importance 加权的封顶 coverage 和 gap 公式，required=0 不参与覆盖分。
- `S_capability = 0.75 × S_skills + 0.25 × K_knowledge`。
- `P = 0.70 × S_capability + 0.30 × I`，I 为六维 RIASEC cosine similarity × 100。
- `T_k = 50 + 50 × clip(log2((Recent_k + 20) / (Previous_k + 20)), −1, 1)`，T 为映射主题分数的加权平均。
- `Match(lambda) = (1 − lambda) × P + lambda × T`；moderate 的 lambda=0.15，fast disruption 的 lambda=0.35，仅改变 lambda。
- 0.75/0.25、0.70/0.30、0.15/0.35 和平滑参数 20 都是已确定的原型参数，效果与有效性待验证，不是经过验证的就业预测；SDG 不进入总分，大模型不计算或改写分数。

## O*NET 官方实证核验（访问日期：2026-10-21）

### 版本、格式与下载边界

[官方下载页](https://www.onetcenter.org/database.html)与[版本归档](https://www.onetcenter.org/db_releases.html)显示当前生产版本为 **31.0，发布于 2026 年 8 月**；官方页面只确认到月份，不虚构具体日。提供 Excel、CSV、JSON，归档还列出 Text、SQL 和 RDF 格式。本轮实际下载并用 Python 标准库 csv 检查七份 CSV，不是假设 CSV 存在。31.0 的技能数据分为 Essential Skills 与 Transferable Skills；旧 Interests 文件在 30.3 改名为 Career Interest Types，不能硬编码旧文件名。

原始文件只放在 `/tmp/futureshift-onet-<文件名>`，不加入仓库、不覆盖 synthetic 文件，也未接入评分代码。下面是完整成功下载的文件大小（字节，不含表头的行数）；链接均为实际访问的 31.0 官方文件。

| 官方文件 | 字节 | 数据行数 | SHA-256 |
| --- | --- | --- | --- |
| [essential_skills.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/essential_skills.csv) | 2,328,135 | 18,200 | 68c4d31d8c55077238395dca40cc4e6d32e6a608b5474bb8264b1f98ae415bd7 |
| [transferable_skills.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/transferable_skills.csv) | 6,081,245 | 45,500 | f17d0419e818a3bf2f55076510c76c4aef01cc8f5aee2670d2f44f6f44ac60f7 |
| [knowledge.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/knowledge.csv) | 8,013,560 | 60,060 | 88092e17d16096cdebe292fee4389deb460edda24ae8b4637212c69c71562f55 |
| [career_interest_types.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/career_interest_types.csv) | 1,136,078 | 8,307 | 19f452d51b81a4d59389b500f85baf252563858f596124fe446dd436a9f41206 |
| [occupation_data.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/occupation_data.csv) | 268,030 | 1,016 | a09eae1d6609686e44e05b7290993a1c8b523d8ca224bc0eedc194c855c3ee02 |
| [scales_reference.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/scales_reference.csv) | 1,006 | 33 | bcba23858ce21ecaacbde303a8993e35d46724b4afb8c9ec2b10e04f42adcfc9 |
| [content_model_reference.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/content_model_reference.csv) | 235,856 | 3,006 | 370033744006dbd5df048431d42a402f6741a00a229b6d0f4e4f4249b6399c04 |

另下载官方数据库页面 HTML 到 `/tmp/futureshift-onet-database.html`（用于提取官方文件链接，大小见下方）。初次沙箱 curl 因 DNS 失败；经授权联网后成功。Knowledge 首次下载超时且仅取得部分内容，未用它完成核验；重试后才检查完整 60,060 行。浏览工具尝试旧路径 `/dictionary/31.0/text/skills.html` 失败，随后沿官方下载页找到有效字典；没有把失败路径作为依据。

### 已核实的文件字段与键

[Essential Skills 字典](https://www.onetcenter.org/dictionary/31.0/csv/essential_skills.html)、[Transferable Skills 字典](https://www.onetcenter.org/dictionary/31.0/csv/transferable_skills.html)、[Knowledge 字典](https://www.onetcenter.org/dictionary/31.0/csv/knowledge.html)和实际 CSV 的 15 列一致：

`O*NET-SOC Code`, `Title`, `Element ID`, `Element Name`, `Scale ID`, `Scale Name`, `Data Value`, `N`, `Standard Error`, `Lower CI Bound`, `Upper CI Bound`, `Recommend Suppress`, `Not Relevant`, `Date`, `Domain Source`。

[Career Interest Types 字典](https://www.onetcenter.org/dictionary/31.0/excel/career_interest_types.html)和实际 CSV 有 9 列：上述前 7 列加 `Date`, `Domain Source`；此文件没有 N、CI 或 suppression 列，不能凭空补出。

| 字段 | 已核实含义与使用方式 |
| --- | --- |
| O*NET-SOC Code | 职业分类标识，按字符串保留点号与尾部零；关联 occupation_data.csv 的职业标题与描述 |
| Element ID | Content Model 元素位置标识，关联 content_model_reference.csv；不能只按显示名称跨领域合并 |
| Scale ID | 指明该行采用的量表，关联 scales_reference.csv；同一元素 IM 与 LV 是两行不同数据 |
| Data Value | 该职业在该元素与量表上的评分，不是用户自评，也不是已经归一化的值 |
| Recommend Suppress | Y 表示低精度，需阻止未经审查的评分使用；不是“没有记录” |
| Not Relevant | Y 表示不适用于该职业；不能假定对应 Data Value 等于零 |
| Date / Domain Source | 该行更新日期及数据来源；与数据库整体发布月份、下载日期分别保存 |

转换前以 `(O*NET-SOC Code, Element ID, Scale ID)` 查找目标记录，检查重复和冲突；不能遇到重复就任意取第一行。统计字段只描述原始职业数据，不是本产品推荐置信度。

### 已核实的原始量表

以下上下限直接来自已下载的 [scales_reference.csv](https://www.onetcenter.org/dl_files/database/db_31_0_csv/scales_reference.csv)，是量表界限，不是当前样本最大最小值。

| Scale ID | Scale Name | Minimum | Maximum | 使用边界 |
| --- | --- | --- | --- | --- |
| IM | Importance | 1 | 5 | 技能及知识重要性 |
| LV | Level | 0 | 7 | 技能及知识职业要求水平 |
| OI | Occupational Interests | 1 | 7 | 六维 RIASEC 数值画像 |
| IH | Occupational Interest High-Point | 0 | 6 | 高点类别编码，不是连续兴趣强度，不进入余弦计算 |

### 建议转换契约（设计建议，尚未实现或校准）

- 用户技能/知识仍为 `user = response / 4`，只允许问卷整数 0–4；不能对 O*NET 原值调用 normalize_0_4。
- 同职业同 Element ID 的 **IM** 作为 importance：`importance = (IM − 1) / 4`；归一化范围 0–1，IM=1 得到零权重。这是项目选择，不是官方规定的匹配方法，其零权重影响仍待验证。
- 同元素的 **LV** 作为职业要求：`required = LV / 7`。技能与知识都遵循此规则，原始 IM、LV、量表上下限、转换版本和来源行同时保存。
- RIASEC 用户端每维两题均值按 `(mean − 1) / 4` 转为 0–1；职业端只取 OI 六行，逐维 `(OI − 1) / 6`。固定顺序 R/I/A/S/E/C，对应下表 ID，不用 IH 高点代码，不用 Specific Interest Areas 代替。平移归一化会影响余弦形状，需验证与原创问卷的适配性。
- 不改变覆盖、缺口、cosine、能力、个人适配、趋势和情景公式。原始值越界、非数值、字段/必要维度缺失、重复冲突，均报不可用原因，不自动截断、补零、用近似名称或重新分配组件权重。
- 核心字段若有 `Recommend Suppress=Y` 或 `Not Relevant=Y`，建议先标为不可用于完整评分，交人工审查，不把低精度或不适用行当作可靠要求。只有预先记录、审查并冻结的核心子集可进入计算；不能为让某职业得到结果而临时丢弃行。空白质量标记保留未知状态，不能推定与 N 等价。
- 已核实且质量通过的 LV=0 才按既定 required=0 规则排除覆盖分；所有有效权重之和为 0、任一能力组件不可计算或 RIASEC 零向量，保留可算分项但停止完整评分和排名。

**用户自评等级与 O*NET 职业要求属于不同测量体系；转换到 0–1 只对齐数值区间，不代表已完成有效性校准，也不证明某个自评等级等价于某个职业水平。** O*NET 主要反映美国职业体系，不得声称代表马来西亚就业预测。

| RIASEC 维度 | O*NET Element ID | Scale ID |
| --- | --- | --- |
| Realistic | 1.B.1.a | OI |
| Investigative | 1.B.1.b | OI |
| Artistic | 1.B.1.c | OI |
| Social | 1.B.1.d | OI |
| Enterprising | 1.B.1.e | OI |
| Conventional | 1.B.1.f | OI |

### 问卷名称 → 官方 Element ID 精确匹配

对各自领域的实际 CSV 做名称相等比较，并核对 Content Model。11 项 Skills 和 7 项 Knowledge 均匹配，没有无法匹配项，没有使用近似替代。相同名称 Mathematics 在两个领域使用不同 ID。名称存在不意味着已选定职业核心子集或完成量表校准。

| 问卷字段 | Exact Element Name | Element ID | 实际数据文件 | 结果 |
| --- | --- | --- | --- | --- |
| skill_01 | Critical Thinking | 2.A.2.a | essential_skills.csv | 精确匹配 |
| skill_02 | Complex Problem Solving | 2.B.2.i | transferable_skills.csv | 精确匹配 |
| skill_03 | Mathematics | 2.A.1.e | essential_skills.csv | 精确匹配 |
| skill_04 | Programming | 2.B.3.e | transferable_skills.csv | 精确匹配 |
| skill_05 | Science | 2.A.1.f | essential_skills.csv | 精确匹配 |
| skill_06 | Systems Analysis | 2.B.4.g | transferable_skills.csv | 精确匹配 |
| skill_07 | Operations Analysis | 2.B.3.a | transferable_skills.csv | 精确匹配 |
| skill_08 | Technology Design | 2.B.3.b | transferable_skills.csv | 精确匹配 |
| skill_09 | Judgment and Decision Making | 2.B.4.e | transferable_skills.csv | 精确匹配 |
| skill_10 | Writing | 2.A.1.c | essential_skills.csv | 精确匹配 |
| skill_11 | Speaking | 2.A.1.d | essential_skills.csv | 精确匹配 |
| knowledge_01 | Computers and Electronics | 2.C.3.a | knowledge.csv | 精确匹配 |
| knowledge_02 | Mathematics | 2.C.4.a | knowledge.csv | 精确匹配 |
| knowledge_03 | Engineering and Technology | 2.C.3.b | knowledge.csv | 精确匹配 |
| knowledge_04 | Physics | 2.C.4.b | knowledge.csv | 精确匹配 |
| knowledge_05 | Chemistry | 2.C.4.c | knowledge.csv | 精确匹配 |
| knowledge_06 | Biology | 2.C.4.d | knowledge.csv | 精确匹配 |
| knowledge_07 | Administration and Management | 2.C.1.a | knowledge.csv | 精确匹配 |

### 十个职业在 31.0 的覆盖核实

下列名称与代码均在 occupation_data.csv 精确一致。各职业完整表中均有 Essential Skills 20 行、Transferable Skills 50 行（各元素 IM/LV 两行），Knowledge 66 行（33 元素 × 2），Career Interest Types 9 行（六个 OI + 三个 IH）。这是记录覆盖，不是所有字段均通过质量审查。

| O*NET-SOC Code | Exact title | 名称/代码 | 问卷范围内需审查的质量标记 |
| --- | --- | --- | --- |
| 15-2051.00 | Data Scientists | 均存在且一致 | Science LV (Suppress=Y)；Operations Analysis LV (Not Relevant=Y)；Programming LV (Suppress=Y)；Systems Analysis LV (Suppress=Y)；Chemistry LV (Not Relevant=Y)；Biology LV (Not Relevant=Y) |
| 15-2031.00 | Operations Research Analysts | 均存在且一致 | Biology LV (Not Relevant=Y) |
| 15-1252.00 | Software Developers | 均存在且一致 | Science LV (Suppress=Y)；Operations Analysis LV (Suppress=Y)；Programming LV (Suppress=Y)；Physics LV (Suppress=Y, Not Relevant=Y)；Chemistry LV (Suppress=Y, Not Relevant=Y)；Biology LV (Suppress=Y, Not Relevant=Y) |
| 15-1211.00 | Computer Systems Analysts | 均存在且一致 | Physics LV (Suppress=Y)；Chemistry LV (Suppress=Y, Not Relevant=Y)；Biology LV (Suppress=Y, Not Relevant=Y) |
| 15-1212.00 | Information Security Analysts | 均存在且一致 | Chemistry LV (Not Relevant=Y)；Biology LV (Suppress=Y, Not Relevant=Y) |
| 17-2199.08 | Robotics Engineers | 均存在且一致 | 未发现 Y 标记（不等于完成全部质量审查） |
| 17-2199.03 | Energy Engineers, Except Wind and Solar | 均存在且一致 | 未发现 Y 标记（不等于完成全部质量审查） |
| 17-2081.00 | Environmental Engineers | 均存在且一致 | 未发现 Y 标记（不等于完成全部质量审查） |
| 13-1199.05 | Sustainability Specialists | 均存在且一致 | 未发现 Y 标记（不等于完成全部质量审查） |
| 19-1029.01 | Bioinformatics Scientists | 均存在且一致 | Programming LV (Suppress=Y) |

### 许可与署名

[O*NET 31.0 数据库许可](https://www.onetcenter.org/license_db.html)为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，适用于所列可下载数据库文件；允许复制和改编，需注明数据库版本、USDOL/ETA 原始来源、许可链接和修改情况。O*NET® 是 USDOL/ETA 商标，按官方要求使用标记；开发者注册是可选项。数据库许可不自动覆盖 Interest Profiler 题目或其他站点内容；本项目继续使用原创兴趣题。

后续使用真实数据时署名应包含：O*NET® 31.0 Database；U.S. Department of Labor, Employment and Training Administration (USDOL/ETA)；官方数据库及 CC BY 4.0 链接。另明确 FutureShift AI 做了职业/字段筛选、归一化、映射和评分，改编未经 USDOL/ETA 批准、背书或测试。保留逐项变更记录是官方建议，也有助于项目追溯。本轮未修改仓库 LICENSE。

官方数据库页面 HTML：424,353 字节。七份 CSV 总计 18,063,910 字节；未下载全库 ZIP。

## 尚未解决的问题与接入门槛

- 自评与职业要求的跨体系校准、原创 RIASEC 问卷的测量有效性未验证。
- 核心子集和质量标记的人工审查未完成；不能因为十个职业存在，就声称十个都可获得完整分数。
- 需要后续单独实现并测试导入/转换层，保持真实数据与 synthetic 测试数据分开；本轮不改评分代码。
- GitHub 主题映射、SDG/课程映射及 Replit 连通性仍待验证。

## 待验证

1. 具体 GitHub 查询主题、过滤条件、技能映射、计数完整性和归一化规则。
2. O*NET 核心字段子集、质量标记审查和自评量表校准；名称/代码、实际文件、IM/LV/OI 及许可已核实。
3. 已确定的评分参数有效性仍待验证，不再将数值列为待选；当前规则见上方“已确定的原型评分规则”。
4. GitHub 接口在 Replit 中的连通性与匿名限流行为；缓存有效期及文件持久化方式。
5. 学习资源和 SDG 映射；预赛暂不提供有独立证据支持的马来西亚劳动力市场预测。
