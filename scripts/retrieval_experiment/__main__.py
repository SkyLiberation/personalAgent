"""仓库根工程入口；只加载独立工具所需的控制端依赖。"""

from __future__ import annotations

import sys
from pathlib import Path

# 仅安装 requirements-control.txt 时，也从本仓库的唯一源码加载。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from personal_agent.adapters.cli.retrieval_experiment import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
