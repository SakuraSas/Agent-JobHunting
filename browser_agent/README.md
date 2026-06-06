# Browser Agent

`browser_agent` 是 Agent-JobHunting 的离线岗位采集模块。它负责定期采集公开招聘信息，转换为统一岗位结构，并通过同步脚本增量写入 `langchain_agent/data/app.db` 和 Chroma 向量库。

采集任务不在用户聊天过程中触发，避免对话时等待爬虫。

## 当前数据源

配置文件：

```text
browser_agent/config/sources.json
```

当前启用两个数据源：

| source | 页面 | 采集方式 | 当前限制 |
|---|---|---|---|
| `xiaomi_campus_browser` | 小米校招 | Playwright 打开页面，监听公开岗位 API，并点击分页 | 按配置同步 |
| `uestc_internship_browser` | 电子科大就业网实习招聘 | Playwright 打开页面，在页面上下文中调用公开 POST 分页接口 | 10 页，每页 20 条，最多 200 条 |

电子科大实习招聘页面：

```text
https://jiuye.uestc.edu.cn/career/recruitment/internship
```

公开接口：

```text
POST https://jiuye.uestc.edu.cn/career/api/home/recruitmentList
```

请求体核心参数：

```json
{
  "type": "INTERNSHIP_RECRUITMENT",
  "timeRange": "ALL",
  "pageIndex": 1,
  "pageSize": 20,
  "isSearchPage": false,
  "searchParams": []
}
```

## 初始化

```powershell
cd E:\UESTC\实习\LangChain_Agent\JobHunting\browser_agent
uv sync
uv run playwright install chromium
```

## 预览抓取

预览只生成 JSON，不写 SQLite 和 Chroma。

小米校招：

```powershell
uv run python scripts/run_browser_agent.py --source xiaomi_campus_browser
```

电子科大实习招聘：

```powershell
uv run python scripts/run_browser_agent.py --source uestc_internship_browser
```

主要输出：

```text
browser_agent/output/latest_browser_jobs.json
browser_agent/output/api/<source>/page_*.json
browser_agent/output/snapshots/<source>/*.txt
```

## 正式同步

正式同步会写入：

```text
langchain_agent/data/app.db
langchain_agent/data/chroma/
langchain_agent/data/source_sync_logs
langchain_agent/data/job_review_queue
```

小米校招：

```powershell
uv run python scripts/browser_sync_jobs.py --source xiaomi_campus_browser
```

电子科大实习招聘：

```powershell
uv run python scripts/browser_sync_jobs.py --source uestc_internship_browser
```

同步流程：

```text
Playwright 打开公开页面
        ↓
监听公开 API 或在页面上下文调用公开 API
        ↓
分页读取 JSON
        ↓
转换为 ExtractedJobCandidate
        ↓
高质量岗位写入 SQLite jobs
        ↓
低质量岗位写入 job_review_queue
        ↓
增量同步 Chroma
        ↓
写入 source_sync_logs / source_sync_state
```

## 电子科大实习招聘说明

第一版只采集接口中的结构化字段，不解析附件正文。

已使用字段包括：

- 公司名称
- 招聘类型
- 工作地点
- 发布时间
- 简历截止时间
- 学历要求
- 岗位类别
- 公司介绍
- 附件名称
- 投递/宣讲链接
- 联系人、电话、邮箱

注意：电子科大就业网部分岗位的完整岗位职责和要求在 `.doc`、`.docx`、`.pdf`、`.xls`、`.xlsx` 附件里。当前版本会把附件名称写入 `requirements`，但不会读取附件正文。字段不完整的岗位会进入审核队列。

当前配置：

```json
{
  "name": "uestc_internship_browser",
  "api_page_size": 20,
  "api_max_pages": 10,
  "max_detail_jobs": 200
}
```

也就是最多采集前 200 条实习招聘。

## 修改采集页数

修改：

```text
browser_agent/config/sources.json
```

找到：

```json
"name": "uestc_internship_browser"
```

调整：

```json
"api_page_size": 20,
"api_max_pages": 10,
"max_detail_jobs": 200
```

如果要抓 20 页，可以改成：

```json
"api_max_pages": 20,
"max_detail_jobs": 400
```

不建议一次性抓取全部 4000+ 条实习招聘，容易让 Chroma 检索噪声变大，也会增加同步时间。

## 定时任务

注册 Windows 定时任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/register_browser_sync_task.ps1
```

当前脚本默认同步哪个 source，取决于 `scripts/run_browser_sync.ps1` 中调用的参数。若要让定时任务同步电子科大实习招聘，需要将脚本里的 source 改为：

```powershell
uv run python scripts/browser_sync_jobs.py --source uestc_internship_browser
```

## 合规边界

- 只采集无需登录即可访问的公开招聘信息。
- 不绕过验证码、登录、限流或反爬限制。
- 新增数据源前先检查页面公开性、robots.txt 和访问频率。
- robots.txt 缺失时，必须人工确认该页面公开且适合低频采集，再设置 `allow_missing_robots_txt=true`。
- 第三方站点搜索页如果 robots.txt 明确禁止，不作为自动爬取入口。

## 代码结构

```text
config/sources.json                         数据源配置
scripts/run_browser_agent.py                预览抓取
scripts/browser_sync_jobs.py                正式增量同步
scripts/register_browser_sync_task.ps1      注册定时任务
src/job_browsing_agent/runner.py            浏览器调度、API 监听、直接 API 分页
src/job_browsing_agent/api_extractors.py    API 字段转换
src/job_browsing_agent/adapters.py          详情页兜底解析
src/job_sync/models.py                      统一岗位模型
src/job_sync/repository.py                  SQLite 增量同步和审核队列
```
