from pydantic import BaseModel
from pathlib import Path
from typing import Optional


class ProductImage(BaseModel):
    id: str
    name: str
    original_path: Path
    processed_path: Optional[Path] = None
    width: int = 0
    height: int = 0
    has_alpha: bool = False


class ProcessedImage(BaseModel):
    product_id: str
    path: Path
    canvas_size: int
    padding: float = 0.15
