"""
users.daily_quota 数据体检与修复脚本

用法：
  python scripts/check_user_daily_quota.py            # 只输出报告
  python scripts/check_user_daily_quota.py --fix      # 缺失字段按身份补齐

规则：
  - 缺失 daily_quota：普通用户补 1000，管理员(is_admin=true)补 10000
  - 非整数/负数：仅输出异常清单，不自动猜测修复
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient
from app.core.config import settings

DEFAULT_USER_QUOTA = 1000
DEFAULT_ADMIN_QUOTA = 10000


def main() -> int:
    fix = "--fix" in sys.argv
    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[settings.MONGO_DB]
    users = db.users

    total = users.count_documents({})
    missing, invalid = [], []

    for doc in users.find({}, {"username": 1, "is_admin": 1, "daily_quota": 1}):
        username = doc.get("username", str(doc["_id"]))
        is_admin = bool(doc.get("is_admin"))
        quota = doc.get("daily_quota", None)

        if quota is None:
            missing.append((username, is_admin))
            if fix:
                new_value = DEFAULT_ADMIN_QUOTA if is_admin else DEFAULT_USER_QUOTA
                users.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"daily_quota": new_value}},
                )
        elif isinstance(quota, bool) or not isinstance(quota, int) or quota < 0:
            invalid.append((username, is_admin, quota))

    print(f"用户总数: {total}")
    print(f"daily_quota 缺失: {len(missing)}" + (" (已修复)" if fix and missing else ""))
    for username, is_admin in missing:
        print(f"  - {username} (admin={is_admin})")
    print(f"daily_quota 非法(需人工确认): {len(invalid)}")
    for username, is_admin, quota in invalid:
        print(f"  - {username} (admin={is_admin}): {quota!r}")

    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
