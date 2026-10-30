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

class StationImageRequest(RequestModel):
    image_base64: str = Field(max_length=30_000_000)
    table_width_mm: float = Field(default=600.0, gt=0, le=2000)
    table_height_mm: float = Field(default=450.0, gt=0, le=2000)
    marker_size_mm: float = Field(default=50.0, gt=0)

class IndexImageRequest(StationImageRequest):
    sheet_id: str = Field(default="REM_CAM_01", min_length=1, max_length=120)
    material: str = Field(min_length=1)
    thickness_mm: float = Field(ge=0.1, le=50)
    use_live_vision_audit: bool = False
    save_to_warehouse: bool = True
    segmentation_mode: Literal["sam", "local_threshold"] = "sam"
    segmentation_concept: str = "sheet"
    segmentation_object_id: Optional[str] = None
    segmentation_box_px: Optional[List[int]] = None
    use_clahe: bool = False
    review_id: Optional[str] = Field(default=None, min_length=8, max_length=100)
    location: str = Field(default="", max_length=120)

class StockLocationRequest(RequestModel):
    location: str = Field(max_length=120)

class ConfirmCutRequest(RequestModel):
    operator_confirmed: Literal[True]

class OrderStockContext(RequestModel):
    material: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_ -]+$")
    thickness_mm: float = Field(ge=0.1, le=50)
    kerf_mm: float = Field(default=1, ge=0, le=20)

class NaturalLanguageOrderRequest(RequestModel):
    stock: Optional[OrderStockContext] = None
    prompt: str = Field(min_length=1, max_length=20000)
    uploaded_dxf_files: List[str] = Field(default_factory=list)

class StructuredOrderRequest(RequestModel):
    order_id: str = "ORD_UI_01"
    material: str = "steel"
    thickness_mm: float = Field(default=3.0, ge=0.1, le=50)
    kerf_mm: float = 3.0
    parts: List[Dict[str, Any]]

class FullPipelineRequest(RequestModel):
    selected_sheet_ids: Optional[List[str]] = Field(default=None, min_length=1, max_length=10000)
    prompt: Optional[str] = None
    order: Optional[Dict[str, Any]] = None
    coarse_step_mm: float = Field(default=8.0, ge=0.1, le=1000)
    fine_step_mm: float = Field(default=1.0, ge=0.01, le=1000)
    search_iterations: int = Field(default=2, ge=0, le=100)
    search_workers: int = Field(default=2, ge=1, le=4)
    search_seed: int = 17
    commit_cuts_to_db: bool = False
    machine_dialect_prompt: Optional[str] = None
    machine_profile: Literal["ISO_6983_GRBL", "LINUXCNC_LASER"] = "ISO_6983_GRBL"
    lead_in_radius_mm: float = Field(default=0, ge=0, le=10)
    cut_feedrate_mm_min: float = Field(default=1800, gt=0, le=100000)
    pierce_delay_sec: float = Field(default=0.4, ge=0, le=60)
    laser_power_s: int = Field(default=1000, ge=1, le=1000)
    uploaded_dxf_files: List[str] = Field(default_factory=list)
    allow_demo_stock: bool = False
    plan_id: Optional[str] = Field(default=None, min_length=8, max_length=100)
