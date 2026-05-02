from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, Text, func

from app.db.models import Base


class AiFaq(Base):
    __tablename__ = "ai_faq"

    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="general")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AiConfig(Base):
    __tablename__ = "ai_config"

    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False, default="claude")
    api_key = Column(String(300), nullable=True)
    model_name = Column(String(100), nullable=False, default="claude-sonnet-4-6")
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=2000)
    system_prompt = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
