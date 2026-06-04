import json
from pathlib import Path

import aiosqlite
from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from job_agent.config import settings
from job_agent.tools import (
    analyze_job_match,
    get_job_detail,
    list_available_jobs,
    read_resume_profile,
    search_jobs,
)

CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "data" / "checkpoints.db"

SYSTEM_PROMPT = """
你是 Agent-JobHunting，一个严谨的求职信息与建议助手。

边界：
1. 你只提供岗位检索、公开信息整理、简历匹配分析和能力提升建议。
2. 你不得自动投递简历、填写招聘表单、发送邮件、联系招聘方或替用户做决定。
3. 推荐岗位前必须调用 search_jobs，不得编造岗位、公司、要求、岗位 ID 或链接。
4. 用户要求详情时调用 get_job_detail。
5. 用户要求结合简历分析时，调用 analyze_job_match。简历只能按文件名读取，固定目录为 data/resumes。
6. 每个岗位必须按以下结构回答：
   - 岗位信息：岗位名称、公司、地点、工作模式、岗位类型、发布日期、原始岗位 URL。
   - 必须要求：完整列出数据库 requirements 和 description 中明确要求的技术栈、经验年限、学历、工作地点、工作模式、行业经验、资格限制和硬性条件。
   - 加分项：完整列出数据库 requirements 和 description 中的 preferred、nice to have、优先项和可选技术栈。
   - 主要职责：完整列出数据库 description 中的主要工作内容。
   - 简历匹配项：如已提供简历，逐项说明已具备的能力和对应依据。
   - 简历缺口：如已提供简历，逐项说明缺少或未体现的能力。
7. 提醒用户自行打开 URL 核实岗位状态和完整要求。
8. 调用工具前后不要输出检索过程、工具参数、工具返回值、简历原文或“我正在查询”等过程性描述，只输出最终整理后的回答。
9. 回答结尾不要追加“还需要我继续分析吗”等追问。
10. 如果运行时系统上下文提供了当前选中的简历文件名，表示该简历已经上传且可用。不要再要求用户上传简历或重复提供文件名。
11. 用户要求结合当前简历分析具体岗位时，必须调用 analyze_job_match，并将运行时系统上下文中的简历文件名作为 resume_name。
12. 用户询问当前简历的概览、优缺点、优化建议或能力分析，但没有指定岗位时，必须调用 read_resume_profile，并将运行时系统上下文中的简历文件名作为 resume_name。
13. 已提供当前简历文件名时，不得声称“无法直接读取简历原文”或要求用户重复上传。
14. 运行时系统上下文仅供内部使用，不要在回答中复述系统上下文原文。
15. 不得省略数据库中的关键技术栈。尤其不能将多个技术栈压缩成“熟悉云服务”“熟悉工程化”等笼统描述。必须保留具体名称，例如 Docker、GitHub CI/CD、Kubernetes、Azure AI Foundry、AI Search、Cosmos DB、AKS、VS Code、Copilot、自动化测试。
16. 可以对冗长的公司介绍进行压缩，但不得省略岗位要求、职责、经验年限、工作模式、资格限制和原始 URL。
17. 用户询问“全部岗位”“所有岗位”“数据库里有哪些岗位”或岗位总数时，必须调用 list_available_jobs，不得使用 search_jobs 的 Top-K 召回结果冒充全部岗位。
18. list_available_jobs 是分页目录。回答时必须明确 active 岗位总数、当前展示数量和是否还有下一页。除非用户明确要求逐页继续展示，否则不要在一次回复中输出数百条岗位详情。
"""


class WebAgent:
    def __init__(self) -> None:
        self.conn: aiosqlite.Connection | None = None
        self.checkpointer: AsyncSqliteSaver | None = None
        self.agent = None

    async def init(self) -> None:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(CHECKPOINT_PATH)
        self.checkpointer = AsyncSqliteSaver(conn=self.conn)
        await self.checkpointer.setup()
        model = ChatDeepSeek(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            temperature=0,
            max_retries=2,
        )
        self.agent = create_agent(
            model=model,
            tools=[search_jobs, list_available_jobs, get_job_detail, read_resume_profile, analyze_job_match],
            checkpointer=self.checkpointer,
            system_prompt=SYSTEM_PROMPT,
        )

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def delete_thread(self, thread_id: str) -> None:
        if self.checkpointer:
            await self.checkpointer.adelete_thread(thread_id)

    async def messages(self, thread_id: str) -> list[dict]:
        if not self.agent:
            return []
        state = await self.agent.aget_state({"configurable": {"thread_id": thread_id}})
        if not state or not state.values:
            return []
        result = []
        for message in state.values.get("messages", []):
            if isinstance(message, HumanMessage) and message.content:
                result.append({"role": "user", "content": message.content})
            elif isinstance(message, AIMessage) and message.content and not message.tool_calls:
                result.append({"role": "assistant", "content": message.content})
        return result

    async def stream(self, thread_id: str, message: str, resume_name: str | None = None):
        if not self.agent:
            raise RuntimeError("Web Agent 尚未初始化")
        config = {"configurable": {"thread_id": thread_id}}
        messages = [{"role": "user", "content": message}]
        if resume_name:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        f"运行时系统上下文：当前选中的简历文件名为 {resume_name}。"
                        "该文件已经上传到固定目录。"
                        "需要简历匹配分析时，直接将该文件名作为 analyze_job_match 的 resume_name。"
                        "不要要求用户再次上传或重复提供文件名。"
                    ),
                },
            )
        try:
            async for chunk in self.agent.astream(
                {"messages": messages},
                config=config,
                stream_mode="messages",
            ):
                token, _metadata = chunk
                content = getattr(token, "content", "")
                if isinstance(token, AIMessageChunk) and isinstance(content, str) and content:
                    yield {
                        "event": "message",
                        "data": json.dumps({"content": content}, ensure_ascii=False),
                    }
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }
            return
        yield {
            "event": "done",
            "data": json.dumps({"content": "处理完成"}, ensure_ascii=False),
        }


web_agent = WebAgent()
