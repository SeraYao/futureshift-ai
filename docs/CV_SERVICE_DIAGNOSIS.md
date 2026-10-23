# CV 提取真实服务排查（2026-10-23）

## 结论与证据边界

本次没有复现历史超时，不能确认历史网络/远端故障的根因。已确认并处理的是本地有九个重复旧服务、不同端口使用不同 AI 配置的问题；不能据此断言重复进程导致了远端超时。历史错误文案与当前客户端文案不同，存在旧模块或旧会话错误信息的可能，但未读取旧 Python 进程内存，不能确认其当时实际 socket 超时值。

重启前 8514 的服务 PID 34277，启动时间为 10 月 22 日 20:27:14，早于本次代码更新。所有九个进程工作目录均为本项目；启动参数均为 `-m streamlit run app.py`，使用 `127.0.0.1` 和 headless 模式。端口为 8501、8503、8504、8505、8506、8510、8512、8513、8514。其中 8503/8504 为另一个旧模型配置，部分其他端口没有 AI 配置。全部已正常终止，只保留重启后的 8514。

## 最终运行配置

- 工作目录：`~/Documents/GitHub/futureshift-ai`。
- 环境：项目 `.venv/bin/python`，沿用旧 8514 的 AI 配置与凭据，无模型/提供方切换。
- 新进程 PID：38048；端口：8514；URL：`http://127.0.0.1:8514/`。
- 启动方式：项目 Python 的 `-c` 日志初始化入口调用 `streamlit.web.cli.main()`，参数为 `run app.py --server.address 127.0.0.1 --server.port 8514 --server.headless true --browser.gatherUsageStats false`。进程独立于本次命令会话，日志：`/private/tmp/futureshift-streamlit-8514.log`。
- 模型：`Qwen/Qwen3-8B`。
- POST 路由：`https://api.runpod.ai/v2/k7sai0ksjge4nx/openai/v1/chat/completions`；Bearer 认证。模型列表返回同一模型 ID。
- 请求格式：Chat Completions、system/user messages、`temperature=0`、JSON object 响应格式、`max_tokens=2400`。输入为脱敏文本，非 PDF 字节。
- **实际超时为 300 秒（5 分钟），不是 15 秒。**原 8514 和新进程均未设置 `AI_TIMEOUT_SECONDS`；磁盘代码默认 300，新进程启动日志和真实请求日志均确认最终值 300。没有找到当前设置为 15 的证据。Git HEAD 旧客户端为硬编码 30 秒；不把它当成旧进程内存值的证明。
- 无项目 `.env`，应用无 dotenv 加载逻辑。读取顺序为传入 `AIConfig.from_env(mapping)` 的映射（若提供），否则进程环境，再对未设置的超时采用代码默认值。`.env.example` 不参与运行时加载。
- 无 SDK、无客户端自动重试、无应用外层任务截止时间；urllib 使用该值作为 socket 超时，不是全流程墙钟上限。DNS 查询不因此获得单独截止时间。未检测到网页环境中的代理变量，`urllib.request.getproxies()` 也为空。远端网关、worker 的超时设置未获访问，不能排除其他远端限制。

## 真实调用结果

| 检查 | 真实结果 |
| --- | --- |
| DNS | 成功，约 0.004 秒 |
| TCP | 成功，约 0.019 秒 |
| TLS | 成功，约 0.030 秒，TLS 1.3，保留证书和主机名验证 |
| RunPod `/health` | HTTP 200，3 idle/ready、0 initializing/unhealthy/throttled，0 queued/in-progress/failed jobs（检查时快照） |
| `/openai/v1/models` | HTTP 200，返回配置模型 |
| 最小合成文本请求 | HTTP 200，约 1.33 秒；32 token 上限导致 `finish_reason=length`，只证明认证和推理响应可用，不算完整内容提取成功 |
| 合成 PDF → 客户端真实提取 | PDF 784 字节、文本 95 字符非空；约 5.09 秒，HTTP 200、`finish_reason=stop`；187 completion tokens，教育/技能/知识各 1 项通过证据校验 |
| 页面操作 → 真实提取 | AppTest 执行上传、逐文件同意、点击按钮、审核页；真实 HTTP 请求约 5.38 秒成功，画像保持为空 |
| 重启后同一配置再次验证 | 从新进程环境复制配置，AppTest 真实 HTTP 约 5.43 秒成功，完整页面流程约 5.61 秒；超时 300 秒、审核结果有效、画像未改变 |
| 最终网页 | `/` HTTP 200，`/_stcore/health` 返回 `ok` |

AppTest 只桥接了其不支持的浏览器上传控件，未模拟 PDF 解析、HTTP 或模型响应。这不是浏览器自动化，也不是在托管 Streamlit 进程内点击浏览器；真实 UI 请求验证在使用同一虚拟环境及新进程配置的 AppTest 进程执行。可用已注入 AI 环境执行 `.venv/bin/python scripts/check_cv_service.py` 复核；此命令会调用真实服务，可能计费，不自动重试。

认证、模型路由、TLS 与此合成输入的结构化输出均已实测成功；当前没有认证失败、额度不足、限流或 worker 故障证据。未获取 RunPod 后台日志、资源历史、历史请求 ID 或旧超时发生时的阶段耗时，因此无法确认当时是否为冷启动、队列等待、网络读取或旧代码配置问题。健康快照不能证明历史一直正常。本次没有发送真实简历，也没有证明任意长度/复杂度的 CV 均可成功；没有基于猜测调整 timeout。

## 改动和回归

- `src/cv_client.py`：增加安全阶段日志，区分连接/TLS、等待响应头、读取响应体、JSON 解析和证据验证；HTTP 状态错误仍独立分类，不改为超时。不记录异常原文、端点、认证头或请求/响应内容。
- `src/cv_intake.py`：记录 PDF 解析耗时和非空文本长度。保留逐文件同意、失败后文件/同意保留、忙碌状态 finally 复位、手动重试。
- `scripts/check_cv_service.py`：可重复运行的显式真实服务验证，合成 PDF、空画像、一次真实请求。
- `tests/test_cv_intake.py`：增加阶段日志脱敏、读取超时分类、连接超时日志及默认 TLS 校验回归。
- `docs/ARCHITECTURE.md`：校正失败时上传保留的说明，补充真实验证边界和日志使用说明。

模拟/本地回归：`.venv/bin/python -m unittest discover -s tests`，**144 项通过**。真实服务调用成功是上表中单独执行的验证，不以模拟测试通过替代。评分、推荐算法、模型、提供方、TLS 验证和超时值未改；保留原有未提交修改，无 commit/push。
