"""Public HTTP request schemas. Field names are the UI contract."""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

class RequestModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

class UpsertRemnantRequest(RequestModel):
    sheet_id: str
    material: str = "steel"
    thickness_mm: float = Field(default=3.0, ge=0.1, le=50)
    exterior: List[List[float]]
    holes: List[List[List[float]]] = Field(default_factory=list)
    dxf_path: str = ""

class IndexImageRequest(RequestModel):
    sheet_id: str = "REM_CAM_01"
    material: str = "steel"
    thickness_mm: float = Field(default=3.0, ge=0.1, le=50)
    image_base64: str = Field(max_length=30_000_000)
    table_width_mm: float = Field(default=600.0, gt=0, le=2000)
    table_height_mm: float = Field(default=450.0, gt=0, le=2000)
    marker_size_mm: float = Field(default=50.0, gt=0)
    use_live_vision_audit: bool = False
    save_to_warehouse: bool = True
    segmentation_mode: Literal["sam", "local_threshold"] = "sam"
    segmentation_concept: str = "sheet"
    segmentation_object_id: Optional[str] = None
    segmentation_box_px: Optional[List[int]] = None
    use_clahe: bool = False

class NaturalLanguageOrderRequest(RequestModel):
    prompt: str = Field(min_length=1, max_length=20000)
    uploaded_dxf_files: List[str] = Field(default_factory=list)

class StructuredOrderRequest(RequestModel):
    order_id: str = "ORD_UI_01"
    material: str = "steel"
    thickness_mm: float = Field(default=3.0, ge=0.1, le=50)
    kerf_mm: float = 3.0
    parts: List[Dict[str, Any]]

class FullPipelineRequest(RequestModel):
    prompt: Optional[str] = None
    order: Optional[Dict[str, Any]] = None
    coarse_step_mm: float = Field(default=8.0, ge=0.1, le=1000)
    fine_step_mm: float = Field(default=1.0, ge=0.01, le=1000)
    commit_cuts_to_db: bool = False
    machine_dialect_prompt: Optional[str] = None
    machine_profile: Literal["ISO_6983_GRBL"] = "ISO_6983_GRBL"
    uploaded_dxf_files: List[str] = Field(default_factory=list)
    allow_demo_stock: bool = False
