# Agent-JobHunting

基于 LangChain、RAG、DeepSeek、FastAPI 和原生 HTML 的求职岗位研究 Agent。

Agent 只提供公开岗位检索、岗位要求整理、简历匹配分析和能力补充建议，不执行自动投递、填写招聘表单、发送邮件或联系招聘方。用户应打开回答中的原始岗位 URL，自行核实岗位状态并决定是否投递。

岗位回答统一包含：岗位信息、必须要求、加分项、主要职责、简历匹配项和简历缺口。模型可以压缩公司介绍，但不能省略数据库中的关键技术栈、经验年限、工作模式、资格限制和原始 URL。

## 启动网页

在项目根目录执行：

```powershell
uv run uvicorn job_agent.web:app --host 127.0.0.1 --port 8001
```

浏览器访问：

```text
http://127.0.0.1:8001
```

岗位同步后台：

```text
http://127.0.0.1:8001/admin
```

## 上传简历

网页输入框下方提供“上传简历”按钮，支持拖拽上传或选择文件上传：

- 支持 PDF、DOCX 和 TXT。
- 单个文件最大 8 MB。
- 同名文件会覆盖旧版本。
- 文件保存到 `data/resumes/`。
- 可以将简历直接拖到对话输入框，释放后立即上传。
- 输入框下方的“上传简历”按钮会打开简历管理弹窗。
- 已上传简历支持选择和删除，删除前需要二次确认。
- 当前选择的简历会显示在输入框上方，并保存在浏览器本地。
- 发送消息时，当前选中的简历文件名会自动传给 Agent，不需要在对话中重复输入。

对话时只需要告诉 Agent 文件名，例如：

```text
请分析 my_resume.pdf 与 xiaomi-campus-7629619317541325062 的匹配度
```

Agent 只能从固定目录读取文件名对应的简历，不能读取用户提供的任意路径。

## 会话与数据库

- `data/app.db`：岗位数据。
- `data/chroma/`：岗位向量索引。
- `data/sessions.db`：网页会话列表，每条记录使用 `thread_id` 区分。
- `data/checkpoints.db`：`AsyncSqliteSaver` 保存的 Agent 对话状态。

创建会话时会生成新的 `thread_id`。删除会话时，会同时删除会话列表记录和该 `thread_id` 的 checkpoint 历史。

## Web API

- `GET /health`：健康检查。
- `GET /api/resumes`：查看固定简历目录和可用文件。
- `POST /api/resumes/upload`：上传简历。
- `DELETE /api/resumes/{filename}`：删除指定简历。
- `POST /api/sessions`：创建会话。
- `GET /api/sessions`：查询会话列表。
- `DELETE /api/sessions/{thread_id}`：删除指定会话及历史消息。
- `GET /api/sessions/{thread_id}/messages`：查询会话消息。
- `POST /api/chat/send`：使用 SSE 流式返回 Agent 回答。
- `GET /api/admin/sources`：查询数据源最后同步状态。
- `GET /api/admin/sync-logs`：查询同步日志。
- `GET /api/admin/jobs`：查询岗位来源、发布日期和失效状态。
- `GET /api/admin/reviews`：查询待审核岗位。
- `POST /api/admin/reviews/{job_id}/approve`：批准岗位，写入 SQLite 并增量更新 Chroma。
- `POST /api/admin/reviews/{job_id}/ignore`：忽略待审核岗位。

## 回复渲染

前端使用本地静态文件中的 `marked 17.0.1` 和 `DOMPurify 3.4.2` 渲染模型回复：

- 支持 Markdown 标题、列表、表格、引用块、代码和链接。
- 使用 `DOMPurify` 清理模型输出中的 HTML。
- 禁止回复加载图片，避免外部跟踪请求和无效图片。
- 岗位链接会在新窗口打开。

## 定期同步岗位

网页服务读取已经同步到 SQLite 和 Chroma 的岗位。Browser Agent 离线同步入口：

```powershell
cd E:\UESTC\实习\LLm_Lora\Langchain_job\browser_agent
uv run python scripts/browser_sync_jobs.py --source xiaomi_campus_browser
```

Browser Agent 不会在聊天工具调用中运行。高置信度岗位会自动增量写入 SQLite 和 Chroma，
低置信度岗位进入 `job_review_queue`，可以在后台页面批准或忽略。

数据源配置：

```text
E:\UESTC\实习\LLm_Lora\Langchain_job\browser_agent\config\sources.json
```

后台页面展示：

- 数据源名称和最后同步时间。
- 岗位发布日期、最后出现时间、active / inactive 状态。
- 失效原因，例如 `expired`、`missing_from_source`、`duplicate_of:...`。
- 每次同步的抓取数、变化数、失效数、过期数、重复数和错误信息。
- 待审核岗位的来源、置信度、审核原因、原始链接，以及批准或忽略操作。
