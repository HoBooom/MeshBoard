from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

class NoticeBase(BaseModel):
    title: str = Field(..., max_length=255)
    body: Optional[str] = None
    target_role: str = Field(default="all", max_length=50)
    is_active: bool = True
    expires_at: Optional[datetime] = None

class NoticeCreate(NoticeBase):
    pass

class NoticeRead(NoticeBase):
    notice_id: uuid.UUID
    created_by: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}
