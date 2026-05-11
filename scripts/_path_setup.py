"""
共享路径初始化模块。
所有 skills 内的 Python 脚本通过此模块统一设置 sys.path，
避免路径查找逻辑在每个脚本中重复。

用法:
    import sys, os
    _exec_dir = os.path.dirname(os.path.abspath(__file__))
    _scripts_dir = os.path.abspath(os.path.join(_exec_dir, "..", "..", "..", "scripts"))
    if _scripts_dir not in sys.path and os.path.isdir(_scripts_dir):
        sys.path.insert(0, _scripts_dir)
    from _path_setup import init
    init()

init() 会自动添加:
  - ~/.financial-planner/scripts/  （安装后的公共脚本）
  - skills/fp-calculator/scripts/ （计算模块）
"""

import sys
import os


def init():
    """初始化 sys.path，确保 db_query 和 calc 可以导入。"""
    project_root = _find_project_root()

    paths = [
        os.path.expanduser("~/.financial-planner/scripts"),
    ]

    if project_root:
        paths.append(os.path.join(project_root, "skills", "fp-calculator", "scripts"))

    for p in paths:
        p = os.path.abspath(p)
        if p not in sys.path and os.path.isdir(p):
            sys.path.insert(0, p)


def _find_project_root():
    """尝试找到项目根目录（financialPlannerSkills/）。"""
    # 从本文件位置往上找
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(3):
        if os.path.exists(os.path.join(current, "SKILL.md")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None
