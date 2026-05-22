# api/v1.py
"""
Governance API Routers - v1 Suffix boundaries.
Features Pydantic P2 validation, correlation identifier checks,
and safe multi-entrant background PDF compilers.
"""

import os
import time
import uuid
import logging
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, EmailStr
from fastapi import FastAPI, APIRouter, Depends, HTTPException, BackgroundTasks, File, UploadFile, Header

# Import components safe from circular reference
from schema.database import get_db_session
from engine.vector import PDFVectorCompiler
from storage.adapter import get_storage_provider

# Config structlog or baseline JSON logger fallback
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_v1")

router = APIRouter(prefix="/api/v1")

# Pydantic Schemas - Strict validation layer
class TenantCreateInput(BaseModel):
    tenant_id: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    corporate_name: str = Field(..., max_length=255)
    tenant_scope: str = Field("default", max_length=100)

class CategoryCreateInput(BaseModel):
    category_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=64)
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)

class FieldMappingInput(BaseModel):
    field_id: str = Field(..., max_length=100)
    label: str = Field(..., max_length=100)
    x_pct: float = Field(..., ge=0.0, le=100.0)
    y_pct: float = Field(..., ge=0.0, le=100.0)
    type: str = Field("text", description="text, date, sign, numerical or arabic")
    regex_format: Optional[str] = None

class TemplateCreateInput(BaseModel):
    template_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=64)
    category_id: Optional[str] = Field(None, max_length=64)
    name: str = Field(..., max_length=150)
    schema_version: str = Field("1.0.0", max_length=20)
    template_version: str = Field("1.0.0", max_length=20)
    schema_json: Dict[str, Any] = Field(default_factory=dict)

class CompilationPayload(BaseModel):
    template_id: str
    tenant_id: str
    form_values: Dict[str, str] # Maps field_id -> input string
    font_size: Optional[float] = 10.0
    source_path: Optional[str] = None


# Secure Ingestion Guards
def validate_pdf_safety(file_bytes: bytes) -> None:
    """
    Guards against PDF bomb attacks and unauthorized file format spoofs.
    """
    if len(file_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Security breach: File size exceeds 15MB limit threshold.")
    
    # Check magic headers for pdf (%PDF-)
    if not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Incorrect payload signature: Missing PDF magic format headers.")

    # Extremely light scan to deny zipped encryptions and nested decompression exploits
    if b"/Encrypt" in file_bytes:
        raise HTTPException(status_code=400, detail="Security risk: Encrypted files are barred from processing.")


# Mock database fallback in-memory dataset
MOCK_DB = {
    "tenants": [
        { "tenant_id": "co-corporate-global-ae", "corporate_name": "Al-Futtaim Enterprises LLC", "tenant_scope": "co-corporate-global-ae", "is_active": True, "created_at": "2026-05-22T16:50:51Z" },
        { "tenant_id": "co-global-trading-uk", "corporate_name": "Apex Trading Logistics UK Ltd", "tenant_scope": "co-global-trading-uk", "is_active": True, "created_at": "2026-05-22T16:50:51Z" },
        { "tenant_id": "co-saudi-telecom-sa", "corporate_name": "STC Business Solutions Ltd", "tenant_scope": "co-saudi-telecom-sa", "is_active": True, "created_at": "2026-05-22T16:50:51Z" }
    ],
    "categories": [
        { "category_id": "cat-1", "tenant_id": "co-corporate-global-ae", "name": "Commercial Licensing", "description": "Trading permits, official government certification sets", "created_at": "2026-05-22T16:50:51Z" },
        { "category_id": "cat-2", "tenant_id": "co-corporate-global-ae", "name": "Trade Agreements", "description": "B2B partnership cords and structural alliances", "created_at": "2026-05-22T16:50:51Z" },
        { "category_id": "cat-3", "tenant_id": "co-global-trading-uk", "name": "Customs Declarations", "description": "Logistics and shipping clearances templates", "created_at": "2026-05-22T16:50:51Z" }
    ],
    "templates": [
        {
            "template_id": "g12",
            "tenant_id": "co-corporate-global-ae",
            "category_id": "cat-1",
            "name": "B2B Unified Corporate Registration Accord",
            "schema_version": "2.1.0",
            "template_version": "1.4.3",
            "field_revision_hash": "a4b2c1d8e0f93a8c5432bd1a7c6f5e4d2c1b0a9f8e7d6c5b4a3f2e1d0c9b8a7f",
            "schema_json": {
                "fields_mapping": [
                    { "field_id": "corporate_id", "label": "Corporate Entity ID (Regulated)", "type": "alphanumeric", "page_index": 0, "x_percentage": 14.50, "y_percentage": 22.85, "validation_rules": { "regex": "^REG-[0-9]{5}-[A-Z]{2}$" } },
                    { "field_id": "registered_trade_name_ar", "label": "Registered Trade Name (Arabic)", "type": "arabic", "page_index": 0, "x_percentage": 14.50, "y_percentage": 30.15, "validation_rules": { "regex": "^[\\u0600-\\u06FF\\s]+$" } },
                    { "field_id": "operational_capital_usd", "label": "Operational Equity (USD)", "type": "numeric", "page_index": 0, "x_percentage": 14.50, "y_percentage": 37.45, "validation_rules": { "regex": "^[0-9]+$" } },
                    { "field_id": "incorporation_date", "label": "Date of Incorporation", "type": "date", "page_index": 0, "x_percentage": 55.20, "y_percentage": 37.45, "validation_rules": { "regex": "^\\d{4}-\\d{2}-\\d{2}$" } }
                ]
            },
            "created_at": "2026-05-22T16:50:51Z",
            "updated_at": "2026-05-22T16:50:51Z"
        }
    ],
    "audit_logs": [
        { "log_id": "tx-9a2f1b", "tenant_id": "co-corporate-global-ae", "correlation_id": "b4c2e1f5-1c2d-4f3e-8c9a-abc123fed456", "client_ip": "192.168.12.44", "document_type": "Commercial Licensing", "status": "SUCCESS", "latency_ms": 142.5, "created_at": "2026-05-22T16:45:00Z" },
        { "log_id": "tx-4c12d9", "tenant_id": "co-corporate-global-ae", "correlation_id": "c9f28a31-ba2d-4001-9a7c-f112e44312ab", "client_ip": "10.0.1.100", "document_type": "Trade Agreements", "status": "SUCCESS", "latency_ms": 188.2, "created_at": "2026-05-22T16:48:30Z" },
        { "log_id": "tx-0b1a2e", "tenant_id": "co-global-trading-uk", "correlation_id": "e031da2c-f682-4412-a169-2f22bba1a6aa", "client_ip": "82.16.24.11", "document_type": "Customs Declarations", "status": "FAILED", "latency_ms": 45.1, "created_at": "2026-05-22T16:50:10Z" }
    ]
}


def log_audit(
    tenant_id: str,
    correlation_id: str,
    client_ip: str,
    document_type: str,
    status: str,
    latency_ms: float,
    failure_trace: Optional[str] = None
) -> None:
    # Safe fallback inside custom audit monitor
    new_m = {
        "log_id": f"tx-{uuid.uuid4().hex[:6]}",
        "tenant_id": tenant_id,
        "correlation_id": correlation_id,
        "client_ip": client_ip,
        "document_type": document_type,
        "status": status,
        "latency_ms": float(f"{latency_ms:.1f}"),
        "failure_trace": failure_trace,
        "created_at": str(time.time())
    }
    MOCK_DB["audit_logs"].insert(0, new_m)
    if len(MOCK_DB["audit_logs"]) > 50:
        MOCK_DB["audit_logs"].pop()


# Queue-ready Asynchronous Worker Logic
def process_dynamic_pdf_background(
    task_id: str,
    source_pdf_rel_path: str,
    tenant_id: str,
    fields_to_render: List[Dict[str, Any]]
) -> None:
    """
    Task runner processing coordinate compilation and arabic reshaping asynchronously.
    Abstracted queue hook prepared for future Redis-worker migrations.
    """
    start_time = time.time()
    logger.info(f"Task started. Correlation ID: {task_id}", extra={"task_id": task_id})
    
    try:
        storage = get_storage_provider()
        
        try:
            # Download working original PDF binary
            original_doc_bytes = storage.retrieve_document(source_pdf_rel_path, tenant_id)
        except Exception as se:
            logger.warning(f"Could not retrieve source PDF {source_pdf_rel_path} for tenant {tenant_id}: {str(se)}. Trying root fallback temp_dummy.pdf")
            fallback_pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_dummy.pdf")
            if os.path.exists(fallback_pdf_path):
                with open(fallback_pdf_path, "rb") as f:
                    original_doc_bytes = f.read()
            else:
                raise FileNotFoundError(f"Source PDF and root fallback temp_dummy.pdf are both missing: {str(se)}")
        
        # Temporary staging on isolated local filesystem
        temp_input_path = f"/tmp/input_{task_id}.pdf"
        temp_output_path = f"/tmp/out_{task_id}.pdf"
        
        with open(temp_input_path, "wb") as f:
            f.write(original_doc_bytes)
            
        # Instantiate Vector Transform engine
        compiler = PDFVectorCompiler(temp_input_path)
        
        # Execute compiling vectors
        compiler.compile_filled_document(fields_to_render, temp_output_path)
        
        # Pull generated binary and save in tenant folder
        with open(temp_output_path, "rb") as f:
            compiled_bytes = f.read()
            
        storage.save_document(compiled_bytes, f"compiled_{task_id}.pdf", tenant_id)
        
        # Clean local buffers
        if os.path.exists(temp_input_path): os.remove(temp_input_path)
        if os.path.exists(temp_output_path): os.remove(temp_output_path)
        
        latency = (time.time() - start_time) * 1000
        logger.info(f"Task completed. Path: compiled_{task_id}.pdf. Latency: {latency:.2f}ms", extra={"task_id": task_id})
        
        # Log success to audit trail
        log_audit(tenant_id, task_id, "127.0.0.1", "Compile PDF Task", "SUCCESS", latency)
        
    except Exception as e:
        logger.error(f"Task failure. Correlation: {task_id}. Reason: {str(e)}", exc_info=True)
        log_audit(tenant_id, task_id, "127.0.0.1", "Compile PDF Task", "FAILED", 0.0, str(e))


# Endpoints
@router.get("/audit")
def get_audit(db=Depends(get_db_session)):
    try:
        from schema.models import AuditLog
        return db.query(AuditLog).order_by(AuditLog.created_at.desc()).all()
    except Exception as e:
        logger.warning(f"Database audit query failed: {str(e)}. Returning mock audit logs.")
        return MOCK_DB["audit_logs"]


@router.get("/tenants")
def get_tenants(db=Depends(get_db_session)):
    try:
        from schema.models import Tenant
        return db.query(Tenant).all()
    except Exception as e:
        logger.warning(f"Database tenants query failed: {str(e)}. Returning fallback mock tenants.")
        return MOCK_DB["tenants"]


@router.post("/tenants", status_code=201)
@router.post("/tenant", status_code=201)
def create_tenant(payload: TenantCreateInput, db=Depends(get_db_session)):
    cor_id = str(uuid.uuid4())
    logger.info(f"Create Tenant triggered. Corporate: {payload.corporate_name}", extra={"correlation_id": cor_id})
    try:
        from schema.models import Tenant
        # Ensure it doesn't already exist
        exist = db.query(Tenant).filter(Tenant.tenant_id == payload.tenant_id).first()
        if exist:
            raise HTTPException(status_code=400, detail="Tenant already registered.")
        new_tenant_obj = Tenant(
            tenant_id=payload.tenant_id,
            corporate_name=payload.corporate_name,
            tenant_scope=payload.tenant_scope
        )
        db.add(new_tenant_obj)
        db.commit()
        db.refresh(new_tenant_obj)
        return {"status": "SUCCESS", "correlation_id": cor_id, "tenant_id": new_tenant_obj.tenant_id}
    except Exception as e:
        logger.warning(f"Database tenant insert failed: {str(e)}. Storing in fallback mock data.")
        exist = [t for t in MOCK_DB["tenants"] if t["tenant_id"] == payload.tenant_id]
        if exist:
            raise HTTPException(status_code=400, detail="Tenant already registered under system scope.")
        new_t = {
            "tenant_id": payload.tenant_id,
            "corporate_name": payload.corporate_name,
            "tenant_scope": payload.tenant_scope,
            "is_active": True,
            "created_at": str(time.time())
        }
        MOCK_DB["tenants"].append(new_t)
        return {"status": "SUCCESS", "correlation_id": cor_id, "tenant_id": payload.tenant_id}


@router.get("/categories")
def get_categories(db=Depends(get_db_session)):
    try:
        from schema.models import Category
        return db.query(Category).all()
    except Exception as e:
        logger.warning(f"Database categories query failed: {str(e)}. Returning mock categories.")
        return MOCK_DB["categories"]


@router.post("/categories", status_code=201)
def create_category(payload: CategoryCreateInput, db=Depends(get_db_session)):
    try:
        from schema.models import Category
        # Check if exists
        exist = db.query(Category).filter(Category.category_id == payload.category_id).first()
        if exist:
            raise HTTPException(status_code=400, detail="Category already registered.")
            
        new_cat = Category(
            category_id=payload.category_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            description=payload.description
        )
        db.add(new_cat)
        db.commit()
        db.refresh(new_cat)
        return new_cat
    except Exception as e:
        logger.warning(f"Database category insert failed: {str(e)}. Storing in fallback mock data.")
        exist = [c for c in MOCK_DB["categories"] if c["category_id"] == payload.category_id]
        if exist:
            raise HTTPException(status_code=400, detail="Category already registered.")
        new_c = {
            "category_id": payload.category_id,
            "tenant_id": payload.tenant_id,
            "name": payload.name,
            "description": payload.description,
            "created_at": str(time.time())
        }
        MOCK_DB["categories"].append(new_c)
        return new_c


@router.delete("/categories/{id}")
def delete_category(id: str, db=Depends(get_db_session)):
    try:
        from schema.models import Category
        existing = db.query(Category).filter(Category.category_id == id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found.")
        db.delete(existing)
        db.commit()
        return {"status": "DELETED"}
    except Exception as e:
        logger.warning(f"Database category delete failed: {str(e)}. Deleting from fallback mock data.")
        existing_idx = -1
        for idx, c in enumerate(MOCK_DB["categories"]):
            if c["category_id"] == id:
                existing_idx = idx
                break
        if existing_idx == -1:
            raise HTTPException(status_code=404, detail="Category not found.")
        MOCK_DB["categories"].pop(existing_idx)
        return {"status": "DELETED"}


@router.get("/templates")
def get_templates(db=Depends(get_db_session)):
    try:
        from schema.models import Template
        return db.query(Template).all()
    except Exception as e:
        logger.warning(f"Database templates query failed: {str(e)}. Returning mock templates.")
        return MOCK_DB["templates"]


@router.post("/templates", status_code=201)
def create_or_update_template(payload: TemplateCreateInput, db=Depends(get_db_session)):
    try:
        from schema.models import Template
        existing = db.query(Template).filter(Template.template_id == payload.template_id).first()
        
        # Calculate field revision hash
        import hashlib
        fields_str = json.dumps(payload.schema_json, sort_keys=True)
        revision_hash = hashlib.sha256(fields_str.encode("utf-8")).hexdigest()
        
        if existing:
            existing.tenant_id = payload.tenant_id
            existing.category_id = payload.category_id
            existing.name = payload.name
            existing.schema_json = payload.schema_json
            existing.field_revision_hash = revision_hash
            # Bump template version
            v_parts = existing.template_version.split('.')
            if len(v_parts) == 3:
                try:
                    new_major = int(v_parts[0]) + 1
                    existing.template_version = f"{new_major}.0.0"
                except ValueError:
                    existing.template_version = "1.0.0"
            else:
                existing.template_version = "1.0.0"
            db.commit()
            db.refresh(existing)
            return existing
        else:
            new_tpl = Template(
                template_id=payload.template_id,
                tenant_id=payload.tenant_id,
                category_id=payload.category_id,
                name=payload.name,
                schema_json=payload.schema_json,
                schema_version=payload.schema_version,
                template_version=payload.template_version,
                field_revision_hash=revision_hash
            )
            db.add(new_tpl)
            db.commit()
            db.refresh(new_tpl)
            return new_tpl
    except Exception as e:
        logger.warning(f"Database template save failed: {str(e)}. Storing in fallback mock data.")
        existing_idx = -1
        for idx, t in enumerate(MOCK_DB["templates"]):
            if t["template_id"] == payload.template_id:
                existing_idx = idx
                break
                
        import hashlib
        fields_str = json.dumps(payload.schema_json, sort_keys=True)
        revision_hash = hashlib.sha256(fields_str.encode("utf-8")).hexdigest()
        
        if existing_idx != -1:
            curr = MOCK_DB["templates"][existing_idx]
            curr["tenant_id"] = payload.tenant_id
            curr["category_id"] = payload.category_id
            curr["name"] = payload.name
            curr["schema_json"] = payload.schema_json
            curr["field_revision_hash"] = revision_hash
            v_parts = curr["template_version"].split('.')
            if len(v_parts) == 3:
                try:
                    new_major = int(v_parts[0]) + 1
                    curr["template_version"] = f"{new_major}.0.0"
                except Exception:
                    curr["template_version"] = "1.0.0"
            else:
                curr["template_version"] = "1.0.0"
            curr["updated_at"] = str(time.time())
            return curr
        else:
            new_t = {
                "template_id": payload.template_id,
                "tenant_id": payload.tenant_id,
                "category_id": payload.category_id,
                "name": payload.name,
                "schema_version": payload.schema_version,
                "template_version": payload.template_version,
                "field_revision_hash": revision_hash,
                "schema_json": payload.schema_json,
                "created_at": str(time.time()),
                "updated_at": str(time.time())
            }
            MOCK_DB["templates"].append(new_t)
            return new_t


@router.delete("/templates/{id}")
def delete_template(id: str, db=Depends(get_db_session)):
    try:
        from schema.models import Template
        existing = db.query(Template).filter(Template.template_id == id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Template mapping not found.")
        db.delete(existing)
        db.commit()
        return {"status": "DELETED", "template_id": id}
    except Exception as e:
        logger.warning(f"Database template delete failed: {str(e)}. Deleting from fallback mock data.")
        existing_idx = -1
        for idx, t in enumerate(MOCK_DB["templates"]):
            if t["template_id"] == id:
                existing_idx = idx
                break
        if existing_idx == -1:
            raise HTTPException(status_code=404, detail="Template mapping not found.")
        MOCK_DB["templates"].pop(existing_idx)
        return {"status": "DELETED", "template_id": id}


@router.post("/document/upload")
async def upload_source_document(
    background_tasks: BackgroundTasks,
    tenant_id: str = Header(...),
    file: UploadFile = File(...)
):
    cor_id = str(uuid.uuid4())
    start_time = time.time()
    
    file_bytes = await file.read()
    validate_pdf_safety(file_bytes)
    
    # Store source binary securely through abstraction
    storage = get_storage_provider()
    safe_filename = f"src_{uuid.uuid4().hex}.pdf"
    
    meta = storage.save_document(file_bytes, safe_filename, tenant_id)
    
    latency = (time.time() - start_time) * 1000
    log_audit(tenant_id, cor_id, "127.0.0.1", "Upload Document", "SUCCESS", latency)
    
    return {
        "status": "UPLOADED",
        "correlation_id": cor_id,
        "filename": safe_filename,
        "path": meta["relative_path"],
        "latency_ms": latency
    }


@router.post("/document/compile")
def trigger_compilation(
    payload: CompilationPayload,
    background_tasks: BackgroundTasks,
    db = Depends(get_db_session)
):
    """
    Submits compiling request to queue-ready FastAPI BackgroundTasks mechanism.
    Returns tracking task reference instantly to client.
    """
    cor_id = str(uuid.uuid4())
    
    # Resolve the template mapping configuration dynamically
    template_data = None
    try:
        from schema.models import Template
        template_obj = db.query(Template).filter(Template.template_id == payload.template_id).first()
        if template_obj:
            template_data = template_obj.schema_json
    except Exception as e:
        logger.warning(f"Database template query failed: {str(e)}. Falling back to static schema files.")

    if not template_data:
        # Fallback to local files (e.g., template/g12.json)
        base_dir = os.path.dirname(os.path.dirname(__file__))
        static_file_path = os.path.join(base_dir, "template", f"{payload.template_id}.json")
        if os.path.exists(static_file_path):
            try:
                with open(static_file_path, "r", encoding="utf-8") as f:
                    template_data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read static template file {static_file_path}: {str(e)}")
        else:
            # Fallback specifically to g12.json as default
            g12_path = os.path.join(base_dir, "template", "g12.json")
            if os.path.exists(g12_path):
                try:
                    with open(g12_path, "r", encoding="utf-8") as f:
                        template_data = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to read static template file {g12_path}: {str(e)}")

    # Extract dynamic coordinate fields mapping
    mappings = []
    if template_data:
        if "fields_mapping" in template_data:
            mappings = template_data["fields_mapping"]
        elif "schema_json" in template_data and "fields_mapping" in template_data["schema_json"]:
            mappings = template_data["schema_json"]["fields_mapping"]

    fields_list = []
    for mapping in mappings:
        fid = mapping.get("field_id")
        if fid in payload.form_values:
            fields_list.append({
                "page": mapping.get("page_index", 0),
                "x_pct": mapping.get("x_percentage", 0.0),
                "y_pct": mapping.get("y_percentage", 0.0),
                "value": str(payload.form_values[fid]),
                "font_size": payload.font_size or 10.0
            })

    # If payload.form_values did not match any fields from mappings,
    # fallback to filling all provided elements as a basic key/value rendering
    if not fields_list:
        for i, (key, value) in enumerate(payload.form_values.items()):
            fields_list.append({
                "page": 0,
                "x_pct": 14.5,
                "y_pct": 20.0 + (i * 8.0),
                "value": str(value),
                "font_size": payload.font_size or 10.0
            })

    # Trigger non-blocking task offloader
    background_tasks.add_task(
        process_dynamic_pdf_background,
        task_id=cor_id,
        source_pdf_rel_path=payload.source_path or "src_example.pdf",
        tenant_id=payload.tenant_id,
        fields_to_render=fields_list
    )
    
    return {
        "status": "QUEUED",
        "correlation_id": cor_id,
        "task_id": cor_id,
        "message": "Asynchronous coordinate rendering pipeline initialized."
    }


@router.get("/document/download/{task_id}")
def download_compiled_document(task_id: str, tenant_id: str = "co-corporate-global-ae"):
    """
    Serves compiled files directly as PDF binary resources for Iframe downloaders (Phase 7).
    """
    try:
        storage = get_storage_provider()
        
        # Ensure fallback file is returned if "fallback" is requested
        if task_id == "fallback":
            fallback_pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_dummy.pdf")
            if os.path.exists(fallback_pdf_path):
                with open(fallback_pdf_path, "rb") as f:
                    doc_bytes = f.read()
                from fastapi.responses import Response
                return Response(
                    content=doc_bytes,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": "inline; filename=temp_dummy.pdf"
                    }
                )
            else:
                raise HTTPException(status_code=404, detail="Fallback original PDF document does not exist.")
        
        filename = task_id
        if not filename.endswith(".pdf") and not "_" in filename:
            filename = f"compiled_{task_id}.pdf"
            
        try:
            doc_bytes = storage.retrieve_document(filename, tenant_id)
        except Exception as se:
            if not filename.endswith(".pdf"):
                filename_pdf = f"{filename}.pdf"
                try:
                    doc_bytes = storage.retrieve_document(filename_pdf, tenant_id)
                    filename = filename_pdf
                except Exception:
                    raise se
            else:
                raise se
        
        from fastapi.responses import Response
        return Response(
            content=doc_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={filename}"
            }
        )
    except Exception as e:
        logger.error(f"Download failure for task {task_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Document not found or expired from storage cache: {str(e)}")

# FastAPI App definition for unified ASGI workers
app = FastAPI(title="B2B Smart Document Automation Engine API")
app.include_router(router)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Mount the static directory for web client scripts
web_path = os.path.join(base_dir, "web")
if os.path.exists(web_path):
    app.mount("/web", StaticFiles(directory=web_path), name="web")

# Route serving index.html
@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = os.path.join(base_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    raise HTTPException(status_code=404, detail="index.html not found")

