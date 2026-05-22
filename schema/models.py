# schema/models.py
"""
SQLAlchemy 2.0 B2B Multi-Tenant ORM Models.
Strict separation between data persistence structures and API schemas.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, 
    String, 
    Integer, 
    ForeignKey, 
    JSON, 
    DateTime, 
    Float, 
    Boolean
)
from sqlalchemy.orm import relationship
from .database import Base

class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id = Column(String(64), primary_key=True, index=True)
    corporate_name = Column(String(255), nullable=False)
    tenant_scope = Column(String(100), default="default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    categories = relationship("Category", back_populates="tenant", cascade="all, delete-orphan")
    templates = relationship("Template", back_populates="tenant", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="tenant", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    category_id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", back_populates="categories")
    templates = relationship("Template", back_populates="category")


class Template(Base):
    __tablename__ = "templates"

    template_id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id"), nullable=False, index=True)
    category_id = Column(String(64), ForeignKey("categories.category_id"), nullable=True, index=True)
    name = Column(String(150), nullable=False)
    
    # Versioning & Integrity
    schema_version = Column(String(20), nullable=False, default="1.0.0")
    template_version = Column(String(20), nullable=False, default="1.0.0")
    field_revision_hash = Column(String(64), nullable=False) # SHA-256 integrity hash
    schema_json = Column(JSON, nullable=False) # Stores fields, labels, categories, regex, coordinates (X%, Y%)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", back_populates="templates")
    category = relationship("Category", back_populates="templates")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(64), ForeignKey("tenants.tenant_id"), nullable=True, index=True)
    correlation_id = Column(String(64), nullable=False, index=True)
    client_ip = Column(String(45), nullable=True) # Max IPv6 length
    document_type = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False) # SUCCESS or FAILED
    latency_ms = Column(Float, nullable=False)
    failure_trace = Column(String(1000), nullable=True) # Sanitized error traces
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    tenant = relationship("Tenant", back_populates="audit_logs")
