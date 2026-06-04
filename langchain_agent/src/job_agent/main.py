import sys

from job_agent.agent import agent


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = {
        "configurable": {
            "thread_id": "local-user-1",
        }
    }

    print("求职 Agent 已启动。输入 exit 退出。")

    while True:
        message = input("\n你：").strip()

        if not message:
            continue

        if message.lower() in {"exit", "quit"}:
            break

        response = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": message,
                    }
                ]
            },
            config=config,
        )

        print("\nAgent：")
        print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
