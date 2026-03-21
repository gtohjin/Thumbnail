"""
기본 단위 테스트 — API 호출 없이 로컬 로직만 검증

실행:
  cd C:\Users\Admin\Desktop\Thumbnail
  python -m pytest tests/ -v
"""

import json
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from app.schemas.prompt_preset import PresetCollection
from app.services.image_preprocess import ImagePreprocessor
from app.services.preset_manager import PresetManager
from app.services.variation_builder import VariationBuilder


# ── 픽스처 ──────────────────────────────────────────────────

@pytest.fixture
def sample_rgba_image(tmp_path) -> Path:
    """테스트용 RGBA 누끼 이미지 생성"""
    img = Image.new("RGBA", (500, 600), (0, 0, 0, 0))
    # 중앙에 불투명 직사각형 (상품 영역 시뮬레이션)
    for x in range(100, 400):
        for y in range(100, 500):
            img.putpixel((x, y), (200, 100, 50, 255))
    path = tmp_path / "test_product.png"
    img.save(path, "PNG")
    return path


@pytest.fixture
def sample_preset_file(tmp_path) -> Path:
    """테스트용 프리셋 JSON"""
    preset_data = {
        "id": "test_preset",
        "name": "테스트 프리셋",
        "category": "test",
        "canvas_size": 512,
        "global_negative_prompt": "blurry, watermark",
        "presets": [
            {
                "id": "p01",
                "name": "화이트 기본",
                "description": "테스트용",
                "template": "Product photo of {product} on {background}, {shadow} shadow",
                "style_tags": ["clean"],
                "variation_schema": {
                    "background": ["white", "gray"],
                    "shadow": ["soft", "none"],
                    "angle": ["front"],
                    "spacing": ["normal"],
                    "prop": ["none"],
                },
                "weight": 1.0,
            }
        ],
    }
    path = tmp_path / "test_preset.json"
    path.write_text(json.dumps(preset_data, ensure_ascii=False), encoding="utf-8")
    return path


# ── 이미지 전처리 테스트 ──────────────────────────────────────

class TestImagePreprocessor:
    def test_load_and_validate(self, sample_rgba_image):
        preprocessor = ImagePreprocessor(canvas_size=512)
        product = preprocessor.load_and_validate(sample_rgba_image)
        assert product.width == 500
        assert product.height == 600
        assert product.has_alpha is True
        assert product.name == "test_product"

    def test_preprocess_output_size(self, sample_rgba_image, tmp_path):
        preprocessor = ImagePreprocessor(canvas_size=512)
        product = preprocessor.load_and_validate(sample_rgba_image)
        processed = preprocessor.preprocess(product, tmp_path / "out")

        assert processed.canvas_size == 512
        assert processed.path.exists()

        with Image.open(processed.path) as img:
            assert img.size == (512, 512)

    def test_preprocess_creates_square(self, sample_rgba_image, tmp_path):
        preprocessor = ImagePreprocessor(canvas_size=1024)
        product = preprocessor.load_and_validate(sample_rgba_image)
        processed = preprocessor.preprocess(product, tmp_path / "out")

        with Image.open(processed.path) as img:
            w, h = img.size
            assert w == h  # 정사각형 보장


# ── 프리셋 매니저 테스트 ──────────────────────────────────────

class TestPresetManager:
    def test_load_preset(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        assert "test_preset" in manager.list_collections()

    def test_get_collection(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        col = manager.get_collection("test_preset")
        assert col is not None
        assert len(col.presets) == 1
        assert col.presets[0].id == "p01"

    def test_missing_collection_returns_none(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        assert manager.get_collection("nonexistent") is None


# ── Variation Builder 테스트 ─────────────────────────────────

class TestVariationBuilder:
    def test_total_count(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        col = manager.get_collection("test_preset")
        builder = VariationBuilder(seed=42)
        results = builder.build_variations(col, total_count=10)
        assert len(results) == 10

    def test_prompt_has_no_product_placeholder_after_finalize(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        col = manager.get_collection("test_preset")
        builder = VariationBuilder(seed=42)
        results = builder.build_variations(col, total_count=5)

        for _, _, prompt_template in results:
            finalized = builder.finalize_prompt(prompt_template, "스킨케어 세럼")
            assert "{product}" not in finalized
            assert "스킨케어 세럼" in finalized

    def test_variation_keys_present(self, sample_preset_file):
        manager = PresetManager(presets_dir=sample_preset_file.parent)
        col = manager.get_collection("test_preset")
        builder = VariationBuilder(seed=0)
        results = builder.build_variations(col, total_count=4)

        for _, var_dict, _ in results:
            assert "background" in var_dict
            assert "shadow" in var_dict

    def test_exact_20_count(self, tmp_path):
        """실제 smartstore_default 프리셋으로 20장 정확성 검증"""
        preset_path = Path("presets/smartstore_default.json")
        if not preset_path.exists():
            pytest.skip("smartstore_default.json 없음")
        manager = PresetManager(presets_dir=Path("presets"))
        col = manager.get_collection("smartstore_default")
        builder = VariationBuilder(seed=7)
        results = builder.build_variations(col, total_count=20)
        assert len(results) == 20
