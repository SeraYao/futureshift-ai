# FutureShift AI — 预赛问卷

## 状态与边界

设计已记录，尚未实现。预计 3–5 分钟完成，待试填验证。演示只用合成数据，不收集姓名、年龄、性别、联系方式、真实 CV 或原型不会使用的个人信息。开放文本提示不要填写身份信息；评分题无默认值，未回答不是 0。

## 页面 1：背景（不计分）

| 字段 | 选项 | 用途 |
| --- | --- | --- |
| Identity | Current student / Recent graduate | 调整职业探索和入门学习说明 |
| Current or completed field of study | Computing / Engineering / Natural sciences / Mathematics and statistics / Business and management / Social sciences / Arts and humanities / Health / Education / Other | 调整学习示例，不推断能力 |
| Highest/current study level | Certificate / Diploma / Bachelor's / Master's / Doctorate / Other | 调整学习解释，不推断能力或职业资格 |
| Practical exposure | No formal experience / Coursework / Personal project / Internship or work | 调整练习和项目建议，不加分 |
| Optional career goal | 可选开放文本 | 目标说明，不直接计分 |

Other 不要求补充个人信息。开放目标若转换为结构化建议，必须展示已有计分字段原值、新值和原因，用户逐项确认并在页面 6 再确认后才能影响评分；不增加隐藏的目标加分。原型可不启用文本解析。

## 页面 2：通用技能自评（计分）

量表：0 = no exposure；1 = basic awareness；2 = applied with guidance；3 = independently applied；4 = advanced。用户值除以 4 转为 0–1。

映射如下；未下载 31.0 数据，每项 Element ID、Level/Importance 字段及量表上下界均待验证，未经验证不能作为最终计算数据。每个职业仅使用问卷内预先选定并验证的核心技能子集，披露覆盖局限。

| ID | 问卷名称 | O*NET 候选映射 | 状态 |
| --- | --- | --- | --- |
| skill_01 | Critical Thinking | Skills → Critical Thinking | 待验证 |
| skill_02 | Complex Problem Solving | Skills → Complex Problem Solving | 待验证 |
| skill_03 | Mathematics | Skills → Mathematics | 待验证 |
| skill_04 | Programming | Skills → Programming | 待验证 |
| skill_05 | Science | Skills → Science | 待验证 |
| skill_06 | Systems Analysis | Skills → Systems Analysis | 待验证 |
| skill_07 | Operations Analysis | Skills → Operations Analysis | 待验证 |
| skill_08 | Technology Design | Skills → Technology Design | 待验证 |
| skill_09 | Judgment and Decision Making | Skills → Judgment and Decision Making | 待验证 |
| skill_10 | Writing | Skills → Writing | 待验证 |
| skill_11 | Speaking | Skills → Speaking | 待验证 |

## 页面 3：知识领域自评（计分）

沿用 0–4 量表并除以 4。不得把专业名称、学历或经历直接当作能力分数。Mathematics 的 Skills 与 Knowledge 是不同字段，分别回答和解释。

| ID | 问卷名称 | O*NET 候选映射 | 状态 |
| --- | --- | --- | --- |
| knowledge_01 | Computers and Electronics | Knowledge → Computers and Electronics | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_02 | Mathematics | Knowledge → Mathematics | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_03 | Engineering and Technology | Knowledge → Engineering and Technology | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_04 | Physics | Knowledge → Physics | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_05 | Chemistry | Knowledge → Chemistry | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_06 | Biology | Knowledge → Biology | 待验证：31.0 Element ID、Level/Importance 及量表 |
| knowledge_07 | Administration and Management | Knowledge → Administration and Management | 待验证：31.0 Element ID、Level/Importance 及量表 |

## 页面 4：RIASEC 兴趣（计分）

以下为项目原创探索题，不复制职业兴趣测试题，不提供诊断或经验证的心理测量结论。1 = strongly disagree；2 = disagree；3 = neutral；4 = agree；5 = strongly agree。全部正向计分。

| ID | Statement | 维度 |
| --- | --- | --- |
| R1 | I enjoy building a small working object. | Realistic |
| R2 | I like testing how tools work in practice. | Realistic |
| I1 | I enjoy looking for patterns in unfamiliar data. | Investigative |
| I2 | I like comparing explanations for a puzzling result. | Investigative |
| A1 | I enjoy expressing an idea through an original design. | Artistic |
| A2 | I like trying several creative ways to tell a story. | Artistic |
| S1 | I enjoy helping someone understand a difficult idea. | Social |
| S2 | I like working with others to support their learning. | Social |
| E1 | I enjoy presenting a proposal to win support. | Enterprising |
| E2 | I like bringing people together to start an initiative. | Enterprising |
| C1 | I enjoy organizing information into a clear system. | Conventional |
| C2 | I like checking records for consistency and missing details. | Conventional |

各维度取两题均值，再按 `(mean − 1) / 4` 转为 0–1；按 R、I、A、S、E、C 顺序组成向量。职业向量来自 O*NET Interests，字段、量表与转换待验证。I 为 cosine similarity × 100。缺题不补值；全选 1 产生零向量，显示不可计算原因、允许修改，按架构降级。

## 页面 5：学习约束与价值偏好（不进入匹配分）

| 字段 | 选项 | 用途 |
| --- | --- | --- |
| Weekly learning time | 3 / 5 / 8 / 10+ hours | 排程；10+ 保守按 10 小时安排并说明 |
| Target plan length | 4 / 8 / 12 weeks | 时间上限；说明未覆盖缺口 |
| Budget | Free only / Low cost acceptable | 筛选核验资源；展示具体费用，不假定支付授权 |
| Preferred learning language | English / Bahasa Malaysia / Chinese | 优先筛选资源；无相应资源则说明，不伪造翻译 |
| SDG preferences | 17 个 SDG 中最多选三个，可不选 | 展示、主动筛选和学习计划解释 |

语言偏好不代表多语言界面已实现。SDG 不进入匹配分，默认不隐藏最高分职业；主动筛选保留全池分数和排名并标记条件。

## 页面 6：Profile confirmation

分区显示计分与不计分字段：全部技能、知识原值及归一化值，12 个兴趣答案及六维向量；列出职业目录、映射、规则版本和外部快照引用。外部 O*NET 要求、职业兴趣向量与 GitHub 数据只读可追溯，不修改来源事实。

全部用户字段允许返回修改。明确开放文本不直接计分，结构化修改保留确认记录。背景、时间、周数、预算、语言及 SDG 均显示不计分及用途。用户确认后才计算匹配；之后修改需重新确认，生成新画像版本。

## 输入来源与验收（待执行）

- S_skills 来自页面 2，K_knowledge 来自页面 3，I 来自页面 4；S_capability、P 为规则派生。T 来自 GitHub，lambda 来自固定情景，不从背景推断。
- 每个不计分字段有用途和标签；不询问原型不使用的个人信息。
- 用户可查看和修改全部用户评分字段，缺失不静默补值。
- 相同确认画像、数据快照和规则版本结果一致；仅修改背景和偏好不能改变匹配分，可以改变学习解释或主动筛选。
- Skills gaps 与 Knowledge gaps 分别显示；职业名称、代码和来源可追溯。
