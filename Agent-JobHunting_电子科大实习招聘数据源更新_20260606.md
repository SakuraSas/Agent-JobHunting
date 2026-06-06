# Agent-JobHunting 更新记录：电子科大实习招聘数据源

更新时间：2026-06-06

## 1. 更新目标

在现有 Browser Agent 基础上，新增电子科技大学就业网“实习招聘”数据源，并将采集结果写入：

```text
langchain_agent/data/app.db
langchain_agent/data/chroma/
```

该数据源不在聊天过程中触发，而是通过离线同步脚本执行。

## 2. 数据源

页面：

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

## 3. 当前采集范围

当前配置为：

```json
{
  "name": "uestc_internship_browser",
  "api_page_size": 20,
  "api_max_pages": 10,
  "max_detail_jobs": 200
}
```

含义：

```text
最多采集前 10 页
每页 20 条
最多 200 条实习招聘
```

配置位置：

```text
browser_agent/config/sources.json
```

## 4. 采集流程

```text
Playwright 打开电子科大实习招聘公开页面
        ↓
在页面上下文中 fetch 公开 POST 分页接口
        ↓
分页读取 JSON
        ↓
转换为 ExtractedJobCandidate
        ↓
高质量岗位写入 SQLite jobs
        ↓
字段不完整岗位写入 job_review_queue
        ↓
增量同步 Chroma
        ↓
写入 source_sync_logs / source_sync_state
```

## 5. 已解析字段

当前版本解析接口中的结构化字段：

```text
公司名称
招聘类型
工作地点
发布时间
简历截止时间
学历要求
岗位类别
公司介绍
附件名称
投递/宣讲链接
联系人
联系电话
联系邮箱
```

## 6. 局限

电子科大就业网部分实习招聘的完整岗位职责和要求在附件中，例如：

```text
.doc
.docx
.pdf
.xls
.xlsx
```

当前版本不解析附件正文，只把附件名称和公开链接写入岗位要求字段。字段不足或公司介绍过短的记录会进入待审核队列。

## 7. 同步命令

预览抓取，不写数据库：

```powershell
cd E:\UESTC\实习\LangChain_Agent\JobHunting\browser_agent
uv run python scripts/run_browser_agent.py --source uestc_internship_browser
```

正式同步，写入 SQLite 和 Chroma：

```powershell
cd E:\UESTC\实习\LangChain_Agent\JobHunting\browser_agent
uv run python scripts/browser_sync_jobs.py --source uestc_internship_browser
```

## 8. 修改页数

如果需要继续扩大范围，修改：

```text
browser_agent/config/sources.json
```

例如抓 20 页：

```json
{
  "api_page_size": 20,
  "api_max_pages": 20,
  "max_detail_jobs": 400
}
```

不建议一次性抓取全部 4000+ 条实习招聘，原因是：

```text
同步时间会明显增加
Chroma 检索噪声会变大
部分旧岗位可能已经失效
大量附件型岗位缺少完整职责和要求
```

## 9. 相关代码

```text
browser_agent/config/sources.json
browser_agent/src/job_browsing_agent/models.py
browser_agent/src/job_browsing_agent/runner.py
browser_agent/src/job_browsing_agent/api_extractors.py
browser_agent/tests/test_api_extractors.py
```
