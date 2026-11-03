"""每日股票分析额度模型"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class QuotaEntry(BaseModel):
    """单次提交在每日账本中的条目（以提交ID为key存放在 entries 字典中）"""
    idempotency_key_hash: str
    request_hash: str
    cost: int = Field(..., ge=1)
    reserved: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    released: int = Field(default=0, ge=0)
    quota_snapshot: int = Field(..., ge=0)
    status: str = "reserved"  # reserved / settled / released
    task_ids: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None


class QuotaDailyDoc(BaseModel):
    """analysis_quota_daily 集合文档"""
    user_id: str
    business_date: str
    reserved: int = 0
    succeeded: int = 0
    released: int = 0
    last_applied_limit: int = 0
    entries: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReserveResult(BaseModel):
    """预占结果"""
    submission_id: str
    cost: int
    limit: int
    occupied: int
    remaining: int
    business_date: str
    resets_at: str
    task_ids: List[str] = Field(default_factory=list)
    replayed: bool = False
    mode: str = "enforce"
    would_reject: bool = False


class QuotaStatus(BaseModel):
    """当前用户当日额度状态"""
    limit: int
    reserved: int
    succeeded: int
    released: int
    occupied: int
    remaining: int
    business_date: str
    resets_at: str
    enabled: bool = True
    mode: str = "enforce"
