"""
SQLAlchemy ORM Models — Multi-Agent Financial Complaint Governance Engine
"""

import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Numeric, Date,
    DateTime, ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_id            = Column(String, primary_key=True)
    product                 = Column(String, nullable=False)
    sub_product             = Column(String)
    issue                   = Column(String)
    sub_issue               = Column(String)
    narrative               = Column(Text, nullable=False)
    company                 = Column(String)
    state                   = Column(String)
    zip_code                = Column(String)
    company_response        = Column(String)
    timely_response         = Column(String)
    consumer_disputed       = Column(String)
    disputed_flag           = Column(Boolean, default=False)
    date_received           = Column(Date)
    date_sent_to_company    = Column(Date)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())

    pages       = relationship("DocumentPage", back_populates="complaint", cascade="all, delete-orphan")
    votes       = relationship("AgentVote", back_populates="complaint", cascade="all, delete-orphan")
    decision    = relationship("Decision", back_populates="complaint", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Complaint id={self.complaint_id} product={self.product}>"


class DocumentPage(Base):
    __tablename__ = "document_pages"

    page_id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id    = Column(String, ForeignKey("complaints.complaint_id", ondelete="CASCADE"), nullable=False)
    page_num        = Column(Integer, default=1)
    section_type    = Column(String, nullable=False)  # 'header' | 'narrative' | 'tags'
    text_content    = Column(Text, nullable=False)
    token_count     = Column(Integer)
    metadata_json   = Column(JSONB, default=dict)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    complaint   = relationship("Complaint", back_populates="pages")
    embedding   = relationship("Embedding", back_populates="page", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DocumentPage id={self.page_id} section={self.section_type}>"


class Embedding(Base):
    __tablename__ = "embeddings"

    page_id         = Column(UUID(as_uuid=True), ForeignKey("document_pages.page_id", ondelete="CASCADE"), primary_key=True)
    qdrant_point_id = Column(String, unique=True)
    model_name      = Column(String, nullable=False)
    vector_dim      = Column(Integer)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    page = relationship("DocumentPage", back_populates="embedding")

    def __repr__(self):
        return f"<Embedding page_id={self.page_id} model={self.model_name}>"


class AgentVote(Base):
    __tablename__ = "agent_votes"

    vote_id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id    = Column(String, ForeignKey("complaints.complaint_id", ondelete="CASCADE"), nullable=False)
    agent_name      = Column(String, nullable=False)
    round_num       = Column(Integer, default=1)
    score           = Column(Numeric(4, 2), nullable=False)
    confidence      = Column(Numeric(4, 3), nullable=False)
    risk_flags      = Column(JSONB, default=list)
    reasoning       = Column(Text)
    raw_response    = Column(JSONB)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    complaint = relationship("Complaint", back_populates="votes")

    def __repr__(self):
        return f"<AgentVote agent={self.agent_name} score={self.score}>"


class Decision(Base):
    __tablename__ = "decisions"

    decision_id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id        = Column(String, ForeignKey("complaints.complaint_id", ondelete="CASCADE"), unique=True, nullable=False)
    final_score         = Column(Numeric(4, 2))
    ai_decision         = Column(String)   # 'Monetary Relief' | 'Explanation Only' | 'Escalate'
    ai_confidence       = Column(Numeric(4, 3))
    debate_rounds       = Column(Integer, default=0)
    guardrail_applied   = Column(String)
    actual_outcome      = Column(String)
    agreement_flag      = Column(Boolean)
    evaluation_notes    = Column(Text)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    complaint = relationship("Complaint", back_populates="decision")

    def __repr__(self):
        return f"<Decision complaint={self.complaint_id} decision={self.ai_decision}>"


class Config(Base):
    __tablename__ = "config"

    config_id           = Column(Integer, primary_key=True, autoincrement=True)
    version             = Column(Integer, nullable=False, default=1)
    weight_compliance   = Column(Numeric(4, 3), default=0.30)
    weight_fairness     = Column(Numeric(4, 3), default=0.20)
    weight_financial    = Column(Numeric(4, 3), default=0.20)
    weight_fraud        = Column(Numeric(4, 3), default=0.20)
    weight_reputation   = Column(Numeric(4, 3), default=0.10)
    debate_threshold    = Column(Numeric(4, 2), default=2.00)
    cold_start_penalty  = Column(Numeric(4, 3), default=0.15)
    min_similar_cases   = Column(Integer, default=5)
    notes               = Column(Text)
    is_active           = Column(Boolean, default=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version":              self.version,
            "weight_compliance":    float(self.weight_compliance),
            "weight_fairness":      float(self.weight_fairness),
            "weight_financial":     float(self.weight_financial),
            "weight_fraud":         float(self.weight_fraud),
            "weight_reputation":    float(self.weight_reputation),
            "debate_threshold":     float(self.debate_threshold),
            "cold_start_penalty":   float(self.cold_start_penalty),
            "min_similar_cases":    self.min_similar_cases,
        }

    def __repr__(self):
        return f"<Config version={self.version} active={self.is_active}>"


class Metric(Base):
    __tablename__ = "metrics"

    metric_id               = Column(Integer, primary_key=True, autoincrement=True)
    run_date                = Column(Date, default=date.today)
    total_evaluated         = Column(Integer)
    accuracy                = Column(Numeric(5, 4))
    precision_score         = Column(Numeric(5, 4))
    recall_score            = Column(Numeric(5, 4))
    dispute_pred_accuracy   = Column(Numeric(5, 4))
    per_agent_json          = Column(JSONB, default=dict)
    notes                   = Column(Text)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Metric date={self.run_date} accuracy={self.accuracy}>"
