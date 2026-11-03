"""用户每日股票分析额度服务

权威额度来源：users.daily_quota
每日账本：analysis_quota_daily 集合（单文档条件更新保证不超发）
模式：QUOTA_MODE = disabled | observe | enforce
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.core.config import settings
from app.core.database import get_mongo_db
from app.models.quota import QuotaStatus, ReserveResult

logger = logging.getLogger(__name__)

COLLECTION = "analysis_quota_daily"

MODE_DISABLED = "disabled"
MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"
VALID_MODES = {MODE_DISABLED, MODE_OBSERVE, MODE_ENFORCE}

OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_RELEASED = "released"
_VALID_OUTCOMES = {OUTCOME_SUCCEEDED, OUTCOME_RELEASED}

# 预占恢复阈值（分钟），可通过 QUOTA_RESERVED_TTL_MINUTES 覆盖
DEFAULT_RESERVED_TTL_MINUTES = 30


class QuotaConfigError(Exception):
    """用户额度数据非法（缺失/非整数/负数）"""


class QuotaExceededError(Exception):
    """当日额度不足"""

    def __init__(self, detail: Dict[str, Any]):
        super().__init__("DAILY_QUOTA_EXCEEDED")
        self.detail = detail


class IdempotencyConflictError(Exception):
    """同一幂等键对应了不同的请求参数"""


class UnknownWriteResultError(Exception):
    """MongoDB 写入结果无法确认，需要客户端携带原幂等键重试"""


class QuotaUnavailableError(Exception):
    """额度账本不可用"""


class AnalysisQuotaService:
    """每日额度账本服务"""

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def _collection(self):
        return get_mongo_db()[COLLECTION]

    def mode(self) -> str:
        mode = str(getattr(settings, "QUOTA_MODE", MODE_DISABLED) or MODE_DISABLED).lower()
        return mode if mode in VALID_MODES else MODE_DISABLED

    def enabled(self) -> bool:
        return self.mode() != MODE_DISABLED

    def _tz(self) -> ZoneInfo:
        name = str(getattr(settings, "QUOTA_BUSINESS_TZ", "") or getattr(settings, "TIMEZONE", "") or "Asia/Shanghai")
        try:
            return ZoneInfo(name)
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    def business_date(self, dt: Optional[datetime] = None) -> str:
        dt = dt or datetime.now(self._tz())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._tz())
        return dt.astimezone(self._tz()).strftime("%Y-%m-%d")

    def resets_at(self, business_date: str) -> str:
        d = datetime.strptime(business_date, "%Y-%m-%d").replace(tzinfo=self._tz())
        return (d + timedelta(days=1)).isoformat()

    @staticmethod
    def hash_idempotency_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def submission_id_from_key(key: str) -> str:
        return "qsub_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def request_hash(payload: Dict[str, Any]) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def new_task_id() -> str:
        return str(uuid.uuid4())

    async def ensure_indexes(self) -> None:
        col = self._collection()
        await col.create_index(
            [("user_id", 1), ("business_date", 1)],
            unique=True, name="uk_user_business_date",
        )
        await col.create_index("entries.task_ids", name="idx_task_ids")

    # ------------------------------------------------------------------
    # 用户额度读取
    # ------------------------------------------------------------------
    async def _get_user_daily_quota(self, user_id: str) -> int:
        db = get_mongo_db()
        doc = None
        try:
            if ObjectId.is_valid(str(user_id)):
                doc = await db.users.find_one(
                    {"_id": ObjectId(str(user_id))}, {"daily_quota": 1, "username": 1}
                )
            if doc is None:
                doc = await db.users.find_one({"username": str(user_id)}, {"daily_quota": 1})
        except QuotaConfigError:
            raise
        except Exception as e:
            logger.error(f"读取用户额度失败 user_id={user_id}: {e}")
            raise QuotaUnavailableError(str(e))
        if doc is None:
            raise QuotaConfigError(f"用户不存在: {user_id}")
        quota = doc.get("daily_quota")
        if isinstance(quota, bool) or not isinstance(quota, int) or quota < 0:
            raise QuotaConfigError(f"用户 daily_quota 非法: {user_id} -> {quota!r}")
        return quota

    # ------------------------------------------------------------------
    # 预占
    # ------------------------------------------------------------------
    async def reserve(
        self,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
        cost: int,
        task_ids: Sequence[str],
        force: bool = False,
    ) -> ReserveResult:
        """原子预占每日额度。

        force=True（observe 模式）时无条件写入账本，并标记 would_reject。
        """
        mode = self.mode()
        limit = await self._get_user_daily_quota(user_id)
        bdate = self.business_date()
        sub_id = self.submission_id_from_key(idempotency_key)
        key_hash = self.hash_idempotency_key(idempotency_key)
        cost = int(cost)
        task_ids = list(task_ids)
        if cost != len(task_ids):
            task_ids = task_ids[:cost] or [self.new_task_id() for _ in range(cost)]

        col = self._collection()

        # 1) 幂等重放：同键同请求直接返回原结果
        try:
            doc = await col.find_one(
                {"user_id": str(user_id), "business_date": bdate},
                {f"entries.{sub_id}": 1, "reserved": 1, "succeeded": 1, "released": 1},
            )
        except Exception as e:
            raise QuotaUnavailableError(str(e))

        if doc and sub_id in (doc.get("entries") or {}):
            entry = doc["entries"][sub_id]
            if entry.get("request_hash") != request_hash:
                raise IdempotencyConflictError(
                    "同一 Idempotency-Key 对应了不同的请求参数"
                )
            occupied = int(doc.get("reserved", 0)) + int(doc.get("succeeded", 0))
            return ReserveResult(
                submission_id=sub_id,
                cost=int(entry.get("cost", cost)),
                limit=limit,
                occupied=occupied,
                remaining=max(limit - occupied, 0),
                business_date=bdate,
                resets_at=self.resets_at(bdate),
                task_ids=list(entry.get("task_ids") or task_ids),
                replayed=True,
                mode=mode,
            )

        now = datetime.utcnow()
        new_entry = {
            "idempotency_key_hash": key_hash,
            "request_hash": request_hash,
            "cost": cost,
            "reserved": cost,
            "succeeded": 0,
            "released": 0,
            "quota_snapshot": limit,
            "status": "reserved",
            "task_ids": task_ids,
            "created_at": now,
            "updated_at": now,
        }
        entries_update = {
            "$ifNull": [
                "$entries",
                {"$literal": {}},
            ]
        }

        pipeline = [
            {
                "$set": {
                    "user_id": str(user_id),
                    "business_date": bdate,
                    "last_applied_limit": limit,
                    "reserved": {"$add": [{"$ifNull": ["$reserved", 0]}, cost]},
                    "succeeded": {"$ifNull": ["$succeeded", 0]},
                    "released": {"$ifNull": ["$released", 0]},
                    "entries": {
                        "$mergeObjects": [
                            entries_update,
                            {"$literal": {sub_id: new_entry}},
                        ]
                    },
                    "updated_at": now,
                    "created_at": {"$ifNull": ["$created_at", now]},
                }
            }
        ]

        base_filter: Dict[str, Any] = {
            "user_id": str(user_id),
            "business_date": bdate,
        }
        if force:
            update_filter = dict(base_filter)
        else:
            # 原子额度条件：reserved + succeeded + cost <= limit（文档已存在时生效）
            update_filter = dict(base_filter)
            update_filter["$or"] = [
                {"reserved": {"$exists": False}},
                {
                    "$expr": {
                        "$lte": [
                            {"$add": [{"$ifNull": ["$reserved", 0]}, {"$ifNull": ["$succeeded", 0]}]},
                            limit - cost,
                        ]
                    }
                },
            ]

        try:
            result = await col.update_one(
                update_filter, pipeline, upsert=True
            )
        except Exception as e:
            logger.error(f"额度预占写入失败 user_id={user_id}: {e}")
            raise UnknownWriteResultError(str(e))

        if result.matched_count == 0 and result.upserted_id is None:
            # 条件不满足 = 额度不足
            occupied_doc = await col.find_one(base_filter, {"reserved": 1, "succeeded": 1})
            occupied = 0
            if occupied_doc:
                occupied = int(occupied_doc.get("reserved", 0)) + int(occupied_doc.get("succeeded", 0))
            detail = {
                "code": "DAILY_QUOTA_EXCEEDED",
                "limit": limit,
                "occupied": occupied,
                "remaining": max(limit - occupied, 0),
                "requested": cost,
                "business_date": bdate,
                "resets_at": self.resets_at(bdate),
            }
            logger.warning(
                f"额度不足 user_id={user_id} date={bdate} limit={limit} occupied={occupied} requested={cost}"
            )
            raise QuotaExceededError(detail)

        occupied = 0
        try:
            fresh = await col.find_one(base_filter, {"reserved": 1, "succeeded": 1})
            if fresh:
                occupied = int(fresh.get("reserved", 0)) + int(fresh.get("succeeded", 0))
        except Exception:
            occupied = cost

        would_reject = force and occupied > limit
        if would_reject:
            logger.warning(
                f"[observe] 超额放行 user_id={user_id} date={bdate} limit={limit} occupied={occupied} requested={cost}"
            )

        return ReserveResult(
            submission_id=sub_id,
            cost=cost,
            limit=limit,
            occupied=occupied,
            remaining=max(limit - occupied, 0),
            business_date=bdate,
            resets_at=self.resets_at(bdate),
            task_ids=task_ids,
            replayed=False,
            mode=mode,
            would_reject=would_reject,
        )

    # ------------------------------------------------------------------
    # 结算（以 task_id 为幂等单位）
    # ------------------------------------------------------------------
    async def settle(self, task_id: str, outcome: str) -> bool:
        """结算单个任务的额度占用。重复调用安全。"""
        if outcome not in _VALID_OUTCOMES:
            raise ValueError(f"非法结算结果: {outcome}")
        col = self._collection()

        try:
            doc = await col.find_one(
                {"entries.task_ids": task_id},
                {"entries": 1},
            )
        except Exception as e:
            logger.error(f"额度结算查询失败 task_id={task_id}: {e}")
            return False

        if not doc:
            # 无额度关联的旧任务，跳过
            return True

        entries = doc.get("entries") or {}
        sub_id = None
        entry = None
        for sid, e in entries.items():
            if task_id in (e.get("task_ids") or []):
                sub_id, entry = sid, e
                break
        if entry is None:
            return True

        # 已结算的任务不重复计数：用数组元素内的标记判断
        settled_ids = set(entry.get("settled_task_ids") or [])
        if task_id in settled_ids:
            return True

        now = datetime.utcnow()
        inc = {
            "reserved": -1,
            outcome: 1,
            f"entries.{sub_id}.reserved": -1,
            f"entries.{sub_id}.{outcome}": 1,
        }
        update = {
            "$inc": inc,
            "$set": {f"entries.{sub_id}.updated_at": now, "updated_at": now},
            "$addToSet": {f"entries.{sub_id}.settled_task_ids": task_id},
        }
        try:
            # 过滤条件中排除已结算的任务，保证并发下同一 task_id 只结算一次
            res = await col.update_one(
                {
                    "_id": doc["_id"],
                    f"entries.{sub_id}.settled_task_ids": {"$ne": task_id},
                },
                update,
            )
        except Exception as e:
            logger.error(f"额度结算写入失败 task_id={task_id}: {e}")
            return False

        # 若该 entry 全部任务已结算，标记 settled
        try:
            fresh = await col.find_one({"_id": doc["_id"]}, {f"entries.{sub_id}": 1})
            e2 = (fresh.get("entries") or {}).get(sub_id, {}) if fresh else {}
            done = int(e2.get("succeeded", 0)) + int(e2.get("released", 0))
            if done >= int(e2.get("cost", 0)):
                await col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {f"entries.{sub_id}.status": "settled",
                              f"entries.{sub_id}.settled_at": now}},
                )
        except Exception as e:
            logger.warning(f"更新 entry 结算状态失败 {sub_id}: {e}")

        logger.info(
            f"额度已结算 task_id={task_id} outcome={outcome} submission={sub_id}"
        )
        return True

    async def release_all(self, submission_id: str, user_id: str, business_date: Optional[str] = None) -> bool:
        """按提交ID幂等释放全部剩余预占（任务创建失败兜底）。"""
        col = self._collection()
        bdate = business_date or self.business_date()
        try:
            doc = await col.find_one(
                {"user_id": str(user_id), "business_date": bdate},
                {f"entries.{submission_id}": 1},
            )
            if not doc:
                return True
            entry = (doc.get("entries") or {}).get(submission_id)
            if not entry:
                return True
            remaining = int(entry.get("reserved", 0))
            if remaining <= 0:
                return True
            now = datetime.utcnow()
            await col.update_one(
                {"_id": doc["_id"]},
                {
                    "$inc": {
                        "reserved": -remaining,
                        "released": remaining,
                        f"entries.{submission_id}.reserved": -remaining,
                        f"entries.{submission_id}.released": remaining,
                    },
                    "$set": {
                        f"entries.{submission_id}.status": "released",
                        f"entries.{submission_id}.settled_at": now,
                        f"entries.{submission_id}.updated_at": now,
                        "updated_at": now,
                    },
                },
            )
            logger.info(f"额度已整体释放 submission={submission_id} amount={remaining}")
            return True
        except Exception as e:
            logger.error(f"释放额度失败 submission={submission_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    async def get_status(self, user_id: str) -> QuotaStatus:
        limit = await self._get_user_daily_quota(user_id)
        bdate = self.business_date()
        doc = await self._collection().find_one(
            {"user_id": str(user_id), "business_date": bdate},
            {"reserved": 1, "succeeded": 1, "released": 1},
        )
        reserved = int(doc.get("reserved", 0)) if doc else 0
        succeeded = int(doc.get("succeeded", 0)) if doc else 0
        released = int(doc.get("released", 0)) if doc else 0
        occupied = reserved + succeeded
        return QuotaStatus(
            limit=limit,
            reserved=reserved,
            succeeded=succeeded,
            released=released,
            occupied=occupied,
            remaining=max(limit - occupied, 0),
            business_date=bdate,
            resets_at=self.resets_at(bdate),
            enabled=self.enabled(),
            mode=self.mode(),
        )

    # ------------------------------------------------------------------
    # 孤儿预占恢复
    # ------------------------------------------------------------------
    async def recover_stale_reservations(self, ttl_minutes: Optional[int] = None, limit: int = 200) -> Dict[str, int]:
        """扫描长时间停留在 reserved 且任务未落库的 entry，执行释放。

        - 任务存在于 analysis_tasks / Redis 队列：保留预占（由终态结算处理）
        - 任务不存在且预占超时：释放
        """
        ttl = int(ttl_minutes or getattr(settings, "QUOTA_RESERVED_TTL_MINUTES", DEFAULT_RESERVED_TTL_MINUTES))
        cutoff = datetime.utcnow() - timedelta(minutes=ttl)
        col = self._collection()
        stats = {"scanned": 0, "released": 0, "kept": 0, "errors": 0}

        try:
            cursor = col.find({"entries": {"$exists": True}}).limit(2000)
            db = get_mongo_db()
            docs = [d async for d in cursor]
        except Exception as e:
            logger.error(f"恢复扫描失败: {e}")
            stats["errors"] += 1
            return stats

        for doc in docs:
            user_id = doc.get("user_id")
            entries = doc.get("entries") or {}
            for sub_id, entry in entries.items():
                if stats["scanned"] >= limit:
                    return stats
                if entry.get("status") != "reserved":
                    continue
                updated = entry.get("updated_at") or entry.get("created_at")
                if not updated or updated > cutoff:
                    continue
                stats["scanned"] += 1
                task_ids = entry.get("task_ids") or []
                if not task_ids:
                    continue

                # 统计未结算任务中仍然存在的数量
                settled_ids = set(entry.get("settled_task_ids") or [])
                existing = 0
                try:
                    existing = await db.analysis_tasks.count_documents(
                        {"task_id": {"$in": [t for t in task_ids if t not in settled_ids]}}
                    )
                except Exception as e:
                    logger.warning(f"恢复检查任务存在性失败 {sub_id}: {e}")
                    stats["errors"] += 1
                    continue

                if existing > 0:
                    stats["kept"] += 1
                    continue

                # 全部未结算任务都不存在：释放剩余预占
                releasable = int(entry.get("reserved", 0))
                if releasable <= 0:
                    continue
                now = datetime.utcnow()
                try:
                    await col.update_one(
                        {"_id": doc["_id"]},
                        {
                            "$inc": {
                                "reserved": -releasable,
                                "released": releasable,
                                f"entries.{sub_id}.reserved": -releasable,
                                f"entries.{sub_id}.released": releasable,
                            },
                            "$set": {
                                f"entries.{sub_id}.status": "released",
                                f"entries.{sub_id}.updated_at": now,
                                "updated_at": now,
                            },
                        },
                    )
                    stats["released"] += 1
                    logger.info(f"恢复释放孤儿预占 submission={sub_id} amount={releasable}")
                except Exception as e:
                    logger.error(f"恢复释放失败 {sub_id}: {e}")
                    stats["errors"] += 1

        if stats["scanned"]:
            logger.info(f"预占恢复扫描完成: {stats}")
        return stats


_service: Optional[AnalysisQuotaService] = None


def get_quota_service() -> AnalysisQuotaService:
    global _service
    if _service is None:
        _service = AnalysisQuotaService()
    return _service


