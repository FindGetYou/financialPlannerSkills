"""
数据库初始化脚本

用法:
    python db_init.py              # 初始化（幂等，已存在则跳过建表）
    python db_init.py --reset      # 删除旧库重建（危险！会丢弃所有数据）

数据位置: ~/.financial-planner/data.db
"""

import os
import sys
import sqlite3

FP_HOME = os.path.expanduser("~/.financial-planner")
DB_PATH = os.path.join(FP_HOME, "data.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def ensure_dir():
    """创建数据目录（如不存在）"""
    os.makedirs(FP_HOME, exist_ok=True)


def get_connection():
    """获取数据库连接，启用 WAL 模式和 foreign keys"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """执行 DDL，幂等（CREATE TABLE IF NOT EXISTS）"""
    ensure_dir()

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()

        # 幂等迁移：为已有数据库添加 return_rate 列
        _migrate(conn)

        print(f"[OK] 数据库初始化完成: {DB_PATH}")
    except Exception as e:
        print(f"[ERROR] 初始化失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def _migrate(conn):
    """幂等迁移：检查并添加缺失的列"""
    try:
        conn.execute("ALTER TABLE asset_records ADD COLUMN return_rate REAL")
        print("[OK] 迁移: asset_records 添加 return_rate 列")
    except Exception:
        pass  # 列已存在


def reset_db():
    """删除并重建数据库"""
    confirm = input("⚠️  这将删除所有财务数据，确定吗？输入 YES 确认: ")
    if confirm != "YES":
        print("已取消")
        return

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[OK] 已删除旧库: {DB_PATH}")

    # 同时删除 WAL/SHM 文件
    for suffix in ["-wal", "-shm"]:
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    init_db()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_db()
    else:
        init_db()
