from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def init_db(db_path: str) -> None:
    global _engine, _SessionLocal
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    _SessionLocal = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)
    logger.info("DB 초기화 완료: %s", db_path)


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("DB가 초기화되지 않았습니다. init_db()를 먼저 호출하세요.")
    return _SessionLocal()
