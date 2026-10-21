# FutureShift AI — 预赛提交准备

Navigate change. Shape your future.

定位：帮助用户为多种可能的职业未来做好准备。预赛聚焦学生与应届毕业生。

## 六项必需交付物

1. PRD（Product Requirements Document）
2. Pitch deck
3. Live prototype
4. Technical and tools declaration（技术与工具声明）
5. GitHub repository
6. 5–7 minute YouTube video

仓库内 `docs/PRD.md` 是工作文档。最终提交 PRD 必须遵循官方提交模板，并再次核对格式、篇幅及递交方式；本目录未包含官方模板。交付物清单按项目提交要求保留，领域 brief 不包含上述全部递交细则，不应推定其已全部核实。

## 官方六项必备功能覆盖检查表

依据 `docs/reference/domain-1-brief.pdf` 第 5 页（PDF 页码）。预赛提案需说明六项实现方式，并现场展示最重要功能的粗略可运行版本；不要求此刻已有完整产品。

| 检查 | 官方功能 | 文档覆盖与计划证据 | 当前状态 |
| --- | --- | --- | --- |
| [ ] | Skills profile intake | 问卷 → 确认合成画像；见 PRD 流程和验收 1 | 计划中，未实现 |
| [ ] | AI-trend signal layer | 可更新来源、日期、快照、计算信号；见 DATA_SOURCES 验证门槛 | 计划中，来源待验证 |
| [ ] | Future-role matching | 规则计算前五职业、分项分数、缺口及更新对比；见 ARCHITECTURE 匹配引擎 | 计划中，未实现 |
| [ ] | Personalised reskilling pathway | 有序步骤、预计时间、已核验免费/低价资源 | 计划中，资源待验证 |
| [ ] | SDG mapping | 每个职业与技能的 SDG、具体 target 和贡献解释 | 计划中，映射待验证 |
| [ ] | Handling uncertainty | moderate / fast AI disruption、透明参数和估计声明 | 计划中，参数待验证 |

## 核心演示准备

固定同一合成画像、情景、目录及评分版本，以不同日期的真实来源快照驱动信号、分数和名次变化；展示变化原因与原始引用。验收不能只替换页面文案。历史回放必须标明回放；合成敏感性测试必须标明测试，不能冒充实时趋势。无真实变化时如实说明，不能人为改排名。

演示只用合成画像，禁止真实 CV 或个人资料。每项推荐均有可核验来源，不编造职业、课程或统计。AI 支持用户判断，不替用户决定职业。技术声明应记录实际使用的栈、模型 ID、来源、许可证、估计与降级方式，不能将建议方案写成已使用工具。

## 当前完成度与提交前核对

已完成开发前文档；尚无应用代码、可运行原型或验收结果。提案中分开标注“已实现”“计划中”“待验证”。正式递交前需逐项核对六项交付物，确保仓库可供评委访问、内容对应实际演示，视频时长为 5–7 分钟，且 PRD 使用官方模板。上述事项均尚未完成核验。
