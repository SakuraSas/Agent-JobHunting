import json
import sys

from job_agent.rag import sync_index


def main() -> None:
    changed_ids = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
    inactive_ids = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    sync_index(changed_ids, inactive_ids)


if __name__ == "__main__":
    main()

