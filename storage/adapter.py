# storage/adapter.py
"""
Storage Service Abstraction Engine.
Decouples file reading and writing from specific storage backends (Local vs Supabase).
Extends strict B2B governance limits on allowed size limits and content structures.
"""

import os
from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Any, Type

class DocumentStorageProtocol(ABC):
    @abstractmethod
    def save_document(self, file_content: bytes, filename: str, tenant_id: str) -> Dict[str, Any]:
        """
        Saves file to memory context or disk, returning metadata mapping.
        """
        pass

    @abstractmethod
    def retrieve_document(self, file_path: str, tenant_id: str) -> bytes:
        """
        Reads binary content of a stored file.
        """
        pass

    @abstractmethod
    def delete_document(self, file_path: str, tenant_id: str) -> bool:
        """
        Permanently expunges doc from registry.
        """
        pass


class LocalFileSystemStorageAdapter(DocumentStorageProtocol):
    """
    Local sandbox storage implementation. Satisfies storage protocol.
    """
    def __init__(self, base_directory: str = "/tmp/smart_doc_storage"):
        self.base_dir = base_directory
        os.makedirs(self.base_dir, exist_ok=True)

    def _resolve_tenant_path(self, tenant_id: str, filename: str) -> str:
        tenant_folder = os.path.join(self.base_dir, tenant_id)
        os.makedirs(tenant_folder, exist_ok=True)
        return os.path.join(tenant_folder, filename)

    def save_document(self, file_content: bytes, filename: str, tenant_id: str) -> Dict[str, Any]:
        # Enforce file limit sizes on ingestion (e.g. 15MB maximum)
        max_limit = 15 * 1024 * 1024
        if len(file_content) > max_limit:
            raise ValueError("Payload size exceeds 15MB limit restriction.")
            
        target_path = self._resolve_tenant_path(tenant_id, filename)
        with open(target_path, "wb") as f:
            f.write(file_content)

        return {
            "storage_provider": "local",
            "relative_path": f"{tenant_id}/{filename}",
            "absolute_path": target_path,
            "byte_size": len(file_content)
        }

    def retrieve_document(self, file_path: str, tenant_id: str) -> bytes:
        # Prevent path traversal attacks (Sandbox confinement validation)
        normalized_path = os.path.normpath(file_path)
        if normalized_path.startswith("..") or os.path.isabs(normalized_path):
            raise PermissionError("Directory escape block triggered.")

        target_path = os.path.join(self.base_dir, tenant_id, file_path)
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Selected block is unreachable: {file_path}")

        with open(target_path, "rb") as f:
            return f.read()

    def delete_document(self, file_path: str, tenant_id: str) -> bool:
        try:
            target_path = os.path.join(self.base_dir, tenant_id, file_path)
            if os.path.exists(target_path):
                os.remove(target_path)
                return True
            return False
        except Exception:
            return False


class SupabaseStorageAdapter(DocumentStorageProtocol):
    """
    Production-grade Supabase bucket storage adapter.
    """
    def __init__(self, supabase_client: Any, bucket_name: str = "documents"):
        self.client = supabase_client
        self.bucket = bucket_name

    def save_document(self, file_content: bytes, filename: str, tenant_id: str) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Supabase client is uninitialized.")
            
        destination_path = f"{tenant_id}/{filename}"
        
        try:
            # Upload payload using Supabase Storage Python adapter
            response = self.client.storage.from_(self.bucket).upload(
                path=destination_path,
                file=file_content,
                file_options={"cache-control": "3600", "upsert": "true"}
            )
            return {
                "storage_provider": "supabase",
                "relative_path": destination_path,
                "byte_size": len(file_content)
            }
        except Exception as e:
            raise RuntimeError(f"Supabase upload pipeline aborted: {str(e)}")

    def retrieve_document(self, file_path: str, tenant_id: str) -> bytes:
        if not self.client:
            raise RuntimeError("Supabase client is uninitialized.")
            
        full_remote_path = f"{tenant_id}/{file_path}"
        try:
            # Fetch directly from cloud container
            response = self.client.storage.from_(self.bucket).download(full_remote_path)
            return response
        except Exception as e:
            raise FileNotFoundError(f"Could not retrieve dynamic asset {file_path}: {str(e)}")

    def delete_document(self, file_path: str, tenant_id: str) -> bool:
        if not self.client:
            return False
        full_remote_path = f"{tenant_id}/{file_path}"
        try:
            self.client.storage.from_(self.bucket).remove([full_remote_path])
            return True
        except Exception:
            return False


# Global Factory Pattern for Storage Ingestion
def get_storage_provider() -> DocumentStorageProtocol:
    """
    Switches between local filesystem and Supabase dynamically
    based on the state of environmental keys.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
    
    if supabase_url and supabase_key:
        try:
            from supabase import create_client
            client = create_client(supabase_url, supabase_key)
            return SupabaseStorageAdapter(client)
        except Exception:
            pass
            
    return LocalFileSystemStorageAdapter()
