from pydantic import BaseModel, Field
from typing import Dict, List, Any


class VariationSchema(BaseModel):
    """각 프롬프트 프리셋에서 변형할 수 있는 파라미터 목록"""
    background: List[str] = ["white", "light_gray", "beige"]
    shadow: List[str] = ["none", "soft", "natural"]
    angle: List[str] = ["front", "three_quarter", "slight_top"]
    spacing: List[str] = ["normal", "tight", "wide"]
    prop: List[str] = ["none", "minimal"]


class PromptPreset(BaseModel):
    id: str
    name: str
    description: str
    template: str
    style_tags: List[str] = []
    variation_schema: VariationSchema = Field(default_factory=VariationSchema)
    weight: float = 1.0  # 할당 가중치 (총 20장 분배 시 사용)


class PresetCollection(BaseModel):
    id: str
    name: str
    category: str
    presets: List[PromptPreset]
    global_negative_prompt: str = ""
    canvas_size: int = 1024
