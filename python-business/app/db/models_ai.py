from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime, Text, ForeignKey,
    UniqueConstraint, func,
)

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
    site = Column(String(30), nullable=False, default="default", index=True)
    provider = Column(String(30), nullable=False, default="claude")
    api_key = Column(String(300), nullable=True)
    base_url = Column(String(500), nullable=True)
    model_name = Column(String(100), nullable=False, default="claude-sonnet-4-6")
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=2000)
    system_prompt = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=False)
    rate_limit_per_min = Column(Integer, default=10)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("site", name="uq_ai_config_site"),
    )


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True)
    site = Column(String(30), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    message_count = Column(Integer, default=0)
    token_used = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
