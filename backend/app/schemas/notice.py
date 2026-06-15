from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

NOTICE_CATEGORIES = {"general", "system", "city", "governance", "release", "security"}
NOTICE_PRIORITIES = {"normal", "high", "critical"}


class NoticeBase(BaseModel):
    title: str = Field(..., max_length=255)
    body: Optional[str] = None
    target_role: str = Field(default="all", max_length=50)
    is_active: bool = True
    category: str = Field(default="general", max_length=20)
    priority: str = Field(default="normal", max_length=10)
    pinned: bool = False
    expires_at: Optional[datetime] = None

class NoticeCreate(NoticeBase):
    pass

class NoticeRead(NoticeBase):
    notice_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}
