import uuid
from pathlib import Path
from typing import Tuple

from PIL import Image

from app.config import settings
from app.schemas.product_image import ProcessedImage, ProductImage


class ImagePreprocessor:
    def __init__(self, canvas_size: int = None):
        self.canvas_size = canvas_size or settings.canvas_size

    def load_and_validate(self, image_path: Path) -> ProductImage:
        """누끼 이미지 로드 및 기본 검증"""
        with Image.open(image_path) as img:
            width, height = img.size
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )

            if width < 200 or height < 200:
                raise ValueError(f"이미지 해상도가 너무 낮습니다: {width}x{height} (최소 200x200 권장)")

        product_id = str(uuid.uuid4())[:8]
        return ProductImage(
            id=product_id,
            name=image_path.stem,
            original_path=image_path,
            width=width,
            height=height,
            has_alpha=has_alpha,
        )

    def preprocess(
        self, product: ProductImage, output_dir: Path, padding: float = 0.15
    ) -> ProcessedImage:
        """누끼 이미지를 정사각형 캔버스로 전처리 후 저장"""
        output_dir.mkdir(parents=True, exist_ok=True)

        with Image.open(product.original_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            img = self._fit_to_square_canvas(img, padding=padding)
            img = img.resize((self.canvas_size, self.canvas_size), Image.LANCZOS)

            output_path = output_dir / f"{product.name}_processed.png"
            img.save(output_path, "PNG", optimize=True)

        product.processed_path = output_path
        return ProcessedImage(
            product_id=product.id,
            path=output_path,
            canvas_size=self.canvas_size,
            padding=padding,
        )

    def _fit_to_square_canvas(self, img: Image.Image, padding: float = 0.15) -> Image.Image:
        """알파 채널 기준 상품 영역 감지 → 정사각형 캔버스 중앙 배치"""
        # 알파 채널 기준 상품 bbox 감지
        if img.mode == "RGBA":
            alpha = img.split()[3]
            bbox = alpha.getbbox()
        else:
            bbox = img.getbbox()

        if bbox is None:
            bbox = (0, 0, img.width, img.height)

        cropped = img.crop(bbox)
        crop_w, crop_h = cropped.size

        # 여백 포함 정사각형 사이즈 계산
        max_side = max(crop_w, crop_h)
        pad_px = int(max_side * padding)
        canvas_side = max_side + pad_px * 2

        # 투명 캔버스 생성 후 중앙 배치
        canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
        x_offset = (canvas_side - crop_w) // 2
        y_offset = (canvas_side - crop_h) // 2
        canvas.paste(cropped, (x_offset, y_offset), cropped)

        return canvas

    def get_product_coverage(self, image_path: Path) -> float:
        """전체 이미지 대비 상품(불투명 픽셀) 비율 반환 (0.0~1.0)"""
        with Image.open(image_path) as img:
            if img.mode != "RGBA":
                return 1.0
            alpha = img.split()[3]
            import numpy as np
            arr = np.array(alpha)
            return float((arr > 10).sum() / arr.size)
