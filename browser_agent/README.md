# Browser Agent

`browser_agent` 是 Agent-JobHunting 的离线岗位采集模块。它定时抓取公开招聘页面，
增量更新 SQLite 和 Chroma，不会在用户对话期间运行浏览器。

## 当前数据源

当前仅启用小米校园招聘公开入口：

```text
https://xiaomi.jobs.f.mioffice.cn/campus/?spread=J7NS6YR
```

配置文件：

```text
config/sources.json
```

## 初始化

```powershell
cd E:\UESTC\实习\LLm_Lora\Langchain_job\browser_agent
uv sync
uv run playwright install chromium
```

## 预览抓取

只抓取并生成审核 JSON，不修改数据库：

```powershell
uv run python scripts/run_browser_agent.py --source xiaomi_campus_browser
```

主要输出：

```text
output/latest_browser_jobs.json
output/api/xiaomi_campus_browser/page_*.json
output/snapshots/xiaomi_campus_browser/*.txt
```

## 正式同步

```powershell
uv run python scripts/browser_sync_jobs.py --source xiaomi_campus_browser
```

同步流程：

```text
Playwright 打开公开列表页
→ 监听页面公开岗位 API
→ 点击分页按钮，由网站前端生成合法签名
→ 读取每页 JSON
→ accepted_jobs 增量写入 SQLite 和 Chroma
→ review_jobs 写入 job_review_queue
→ 完整同步成功时，将消失岗位标记为 inactive
→ 写入 source_sync_logs
```

API 缺字段时，系统会回退到详情页可见文本解析。仍不完整的岗位进入审核队列。

## 定时任务

注册 Windows 定时任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/register_browser_sync_task.ps1
```

任务名称：`Agent-JobHunting-BrowserSync`。每 6 小时执行一次，日志写入 `logs/`。

## 合规边界

- 仅抓取无需登录即可访问的公开岗位。
- 不绕过验证码、登录、限流或反爬限制。
- 新增来源前人工检查网站条款和 `robots.txt`。
- `robots.txt` 缺失时默认停止；人工确认公开性后才能显式设置
  `allow_missing_robots_txt=true`。

## 代码结构

```text
config/sources.json                         数据源配置
scripts/run_browser_agent.py                预览抓取
scripts/browser_sync_jobs.py                正式增量同步
scripts/register_browser_sync_task.ps1      注册定时任务
src/job_browsing_agent/runner.py            浏览器调度、API 监听和分页
src/job_browsing_agent/api_extractors.py    API 字段转换
src/job_browsing_agent/adapters.py          详情页兜底解析
src/job_sync/models.py                      统一岗位模型
src/job_sync/repository.py                  SQLite 增量同步和审核队列
```
