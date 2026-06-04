# Agent-JobHunting 技术文档

生成时间：`2026-06-01 14:04:20 +08:00`

## 1. 项目目标

Agent-JobHunting 是一个基于 LangChain、RAG、DeepSeek、FastAPI 和原生 HTML 的求职辅助
系统。系统只提供岗位检索、岗位要求整理、简历匹配分析和能力补充建议，不自动投递简历。

当前岗位数据源仅保留小米校园招聘公开入口：

```text
https://xiaomi.jobs.f.mioffice.cn/campus/?spread=J7NS6YR
```

## 2. 当前目录

```text
Langchain_job/
├─ bge-small/                  本地中文 Embedding 模型
├─ browser_agent/              离线岗位采集与增量同步
├─ langchain_agent/            Web 对话 Agent、RAG 和管理后台
└─ Agent-JobHunting_技术文档_20260601_140420.md
```

旧 Python.org 数据源和旧 `crawl4` 项目已经删除。共享岗位模型与 SQLite 同步仓库已经迁移到
`browser_agent/src/job_sync/`。

## 3. 总体架构

```text
Windows 定时任务
→ Browser Agent 离线抓取公开岗位
→ SQLite 增量同步
→ Chroma 增量同步
→ FastAPI Web 服务
→ LangChain Agent 使用 RAG 检索岗位
→ 用户核实原始 URL 后自行决定是否投递
```

浏览器抓取不会在用户对话期间执行。这样可以避免聊天响应变慢、重复抓取、页面偶发失败影响问答，
以及多个用户同时触发站点请求。

## 4. Browser Agent

### 4.1 核心入口

```text
browser_agent/scripts/run_browser_agent.py       预览抓取，不修改数据库
browser_agent/scripts/browser_sync_jobs.py       正式离线增量同步
browser_agent/scripts/run_browser_sync.ps1       定时任务包装器
browser_agent/scripts/register_browser_sync_task.ps1
```

### 4.2 小米公开 API 分页

小米列表页是 SPA 动态页面。Browser Agent 使用 Playwright 打开公开入口，监听页面请求：

```text
/api/v1/search/job/posts
```

分页流程：

```text
打开公开列表页
→ 监听首屏岗位 JSON
→ 点击页面“下一页”
→ 由网站前端生成合法 _signature
→ 监听后续分页 JSON
→ 将 job_post_list 转换为统一岗位模型
```

不能直接修改首屏 URL 中的 `offset`，因为 `_signature` 与分页参数绑定。当前实现保留页面原本的
交互方式，不绕过站点访问机制。

### 4.3 字段转换

API 字段转换位于：

```text
browser_agent/src/job_browsing_agent/api_extractors.py
```

统一岗位模型位于：

```text
browser_agent/src/job_sync/models.py
```

主要字段：

```text
id、source、title、company、city、job_type
description、requirements、source_url
published_at、status、last_seen_at、inactive_reason
content_hash、dedupe_key
```

### 4.4 详情页兜底

当 API 缺少关键字段时，系统打开岗位详情页，按可见文本解析：

```text
职位描述 → 岗位职责
职位要求 → 任职要求
校招 / 社招元信息 → 城市和岗位类型
```

详情页适配器：

```text
browser_agent/src/job_browsing_agent/adapters.py
```

### 4.5 LLM 兜底

DeepSeek 兜底代码保留在：

```text
browser_agent/src/job_browsing_agent/llm.py
```

默认配置：

```json
{
  "use_llm_fallback": false,
  "llm_concurrency": 2
}
```

小米 API 已提供结构化字段，因此当前同步不调用 LLM。规则和详情页仍无法解析的新数据源，才考虑
启用 DeepSeek。LLM 不应猜测缺失城市或扩写岗位职责。

## 5. 增量同步

正式同步命令：

```powershell
cd E:\UESTC\实习\LLm_Lora\Langchain_job\browser_agent
uv run python scripts/browser_sync_jobs.py --source xiaomi_campus_browser
```

同步过程：

```text
抓取全部公开岗位
→ accepted_jobs 写入 jobs
→ review_jobs 写入 job_review_queue
→ 写入 source_sync_logs 和 source_sync_state
→ 增量写入或删除 Chroma 向量
```

### 5.1 去重

岗位去重键：

```text
公司 + 岗位名称 + 地点 + 原始 URL
```

### 5.2 消失岗位

只有抓取完整成功且不存在 `skipped_urls` 时，才允许将消失岗位标记为：

```text
status=inactive
inactive_reason=missing_from_source
```

待审核岗位虽然不会自动写入正式岗位表，但属于“本次已经看到”的岗位。同步层使用
`seen_job_ids` 防止它们被错误标记为失效。

### 5.3 过期岗位

发布日期支持 ISO 时间戳，包括带微秒的时间。超过配置天数的岗位会标记为：

```text
status=inactive
inactive_reason=expired
```

## 6. 审核队列

质量评分位于：

```text
browser_agent/src/job_browsing_agent/quality.py
```

当前会进入审核区的典型情况：

```text
missing_city
short_description
missing_requirements
missing_company
```

审核表：

```text
job_review_queue
```

管理后台：

```text
http://127.0.0.1:8001/admin
```

后台支持：

- 查看来源、同步时间和同步日志。
- 查看岗位 active / inactive 状态。
- 查看待审核岗位、置信度、原因和原始 URL。
- 批准岗位：写入 SQLite 并增量更新 Chroma。
- 忽略岗位：仅更新审核状态，不污染 RAG。

## 7. JobHunting Agent

启动 Web 服务：

```powershell
cd E:\UESTC\实习\LLm_Lora\Langchain_job\langchain_agent
uv run uvicorn job_agent.web:app --host 127.0.0.1 --port 8001
```

访问：

```text
对话页面：http://127.0.0.1:8001
管理后台：http://127.0.0.1:8001/admin
```

主要数据：

```text
langchain_agent/data/app.db           岗位、同步日志和审核队列
langchain_agent/data/chroma/          岗位向量
langchain_agent/data/sessions.db      会话列表
langchain_agent/data/checkpoints.db   LangGraph 对话 checkpoint
langchain_agent/data/resumes/         用户上传简历
```

### 7.1 简历读取工具

简历固定保存在 `langchain_agent/data/resumes/`。Web 前端会将当前选中的简历文件名随对话
请求传给 Agent。

工具：

```text
list_available_jobs(limit, offset, city, job_type) 数据库 active 岗位目录与总数
search_jobs(query, ...)                            RAG 语义搜索，返回 Top-K 相关岗位
read_resume_profile(resume_name)              简历概览、优缺点和优化建议
analyze_job_match(job_id, resume_name)         具体岗位与简历匹配分析
```

两种工具都只能按文件名读取固定目录中的 PDF、DOCX 或 TXT，不能读取用户提供的任意路径。

`list_available_jobs` 与 `search_jobs` 用途不同：用户询问“全部岗位”或岗位总数时，使用分页
目录工具；用户描述求职需求时，使用 Chroma 语义搜索。Top-K 召回结果不能当作数据库全量岗位。

## 8. 定时任务

注册命令：

```powershell
cd E:\UESTC\实习\LLm_Lora\Langchain_job\browser_agent
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/register_browser_sync_task.ps1
```

当前任务：

```text
任务名称：Agent-JobHunting-BrowserSync
执行间隔：每 6 小时
首次计划执行：2026-06-02 02:00:00
日志目录：browser_agent/logs/
```

## 9. 当前验证状态

清理和增量同步后的状态：

```text
SQLite 岗位：330
active 岗位：300
expired inactive 岗位：30
数据源：xiaomi_campus_browser
待审核岗位：58
Chroma active 向量：300
Python.org 岗位：0
Python.org 向量：0
```

真实全量采集：

```text
method=public_api_pagination
observed=388
accepted=330
review=58
skipped=0
complete=True
```

重复同步：

```text
changed=0
inactive=30
expired=30
```

这一轮同步修正了 ISO 微秒时间戳解析，因此首次识别并下线 30 条过期岗位。后续同步不会重复
删除已经 inactive 的向量。

## 10. 合规与安全

- 仅抓取无需登录即可查看的公开岗位。
- 不绕过登录、验证码、限流或反爬机制。
- 新数据源接入前人工检查网站条款和 `robots.txt`。
- `robots.txt` 缺失时默认停止；确认页面公开后才能显式启用缺失许可。
- `.env`、简历、SQLite 和 Chroma 不应提交到 Git。
- Agent 不自动投递简历，用户必须打开原始 URL 自行核实并决策。

## 11. 后续建议

优先级建议：

1. 在管理后台增加审核筛选、分页和批量批准。
2. 为 RAG 增加固定评估集，检查 URL、失效岗位过滤和简历匹配质量。
3. 新增公开招聘来源时，优先复用 JSON API，再使用详情页适配器兜底。
