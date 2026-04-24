"""
MeshBoard — SQLAlchemy DeclarativeBase

모든 ORM 모델의 공통 베이스 클래스.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 DeclarativeBase — 모든 모델이 이 클래스를 상속합니다."""
    pass
