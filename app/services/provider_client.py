"""
Image Generation Provider Abstraction

지원 Provider:
- openai   : OpenAI DALL-E 2 (images/edits) — 참조 이미지 + 프롬프트 기반 편집
- stability: Stability AI SDXL (img2img) — 참조 이미지 strength 기반 생성
- gemini   : Google Gemini 2.0 Flash Image (나노바나나 AI) — 참조 이미지 + 프롬프트

새 provider 추가 시 BaseImageProvider를 상속해서 generate() 구현 후
get_provider()에 등록하면 됨.
"""

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


@dataclass
class GenerationResult:
    success: bool
    image_data: Optional[bytes] = None
    error: Optional[str] = None


class BaseImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_path: Path,
        negative_prompt: str = "",
    ) -> GenerationResult:
        """참조 이미지 + 텍스트 프롬프트로 이미지 생성"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class OpenAIProvider(BaseImageProvider):
    """
    OpenAI images/edits 엔드포인트 사용 (DALL-E 2).
    - 참조 이미지(RGBA PNG) + 프롬프트 → 편집 이미지 반환
    - 마스크 없이 호출하면 전체 이미지를 참조로 생성
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.openai_api_key
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요.")

    @property
    def name(self) -> str:
        return "openai"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    async def generate(
        self,
        prompt: str,
        reference_image_path: Path,
        negative_prompt: str = "",
    ) -> GenerationResult:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                image_bytes = reference_image_path.read_bytes()

                response = await client.post(
                    "https://api.openai.com/v1/images/edits",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"image": ("image.png", image_bytes, "image/png")},
                    data={
                        "model": "dall-e-2",
                        "prompt": prompt[:1000],
                        "n": 1,
                        "size": "1024x1024",
                        "response_format": "b64_json",
                    },
                )

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:300]}"
                return GenerationResult(success=False, error=error_msg)

            data = response.json()
            image_b64 = data["data"][0]["b64_json"]
            return GenerationResult(success=True, image_data=base64.b64decode(image_b64))

        except Exception as e:
            return GenerationResult(success=False, error=str(e))


class StabilityProvider(BaseImageProvider):
    """
    Stability AI SDXL img2img 엔드포인트 사용.
    - image_strength로 참조 이미지 반영 강도 조절 (0.35 권장)
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.stability_api_key
        if not self.api_key:
            raise ValueError("STABILITY_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요.")
        self.engine_id = "stable-diffusion-xl-1024-v1-0"

    @property
    def name(self) -> str:
        return "stability"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    async def generate(
        self,
        prompt: str,
        reference_image_path: Path,
        negative_prompt: str = "",
    ) -> GenerationResult:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                image_bytes = reference_image_path.read_bytes()

                response = await client.post(
                    f"https://api.stability.ai/v1/generation/{self.engine_id}/image-to-image",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                    },
                    data={
                        "text_prompts[0][text]": prompt,
                        "text_prompts[0][weight]": "1",
                        "text_prompts[1][text]": negative_prompt or "low quality, blurry",
                        "text_prompts[1][weight]": "-1",
                        "image_strength": "0.35",
                        "init_image_mode": "IMAGE_STRENGTH",
                        "cfg_scale": "7",
                        "samples": "1",
                        "steps": "30",
                    },
                    files={"init_image": ("image.png", image_bytes, "image/png")},
                )

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:300]}"
                return GenerationResult(success=False, error=error_msg)

            data = response.json()
            image_b64 = data["artifacts"][0]["base64"]
            return GenerationResult(success=True, image_data=base64.b64decode(image_b64))

        except Exception as e:
            return GenerationResult(success=False, error=str(e))


class GeminiProvider(BaseImageProvider):
    """
    Google Gemini 2.0 Flash Image (나노바나나 AI) 기반 이미지 생성.
    - 참조 이미지(누끼 PNG) + 텍스트 프롬프트 → 새 이미지 생성
    - 동기 SDK를 asyncio executor로 래핑해 비동기 호환
    """

    MODEL = "gemini-3.1-flash-image-preview"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인하세요.")

    @property
    def name(self) -> str:
        return "gemini"

    async def generate(
        self,
        prompt: str,
        reference_image_path: Path,
        negative_prompt: str = "",
    ) -> GenerationResult:
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, self._generate_sync, prompt, reference_image_path, negative_prompt
            )
            return result
        except Exception as e:
            return GenerationResult(success=False, error=str(e))

    def _generate_sync(
        self, prompt: str, reference_image_path: Path, negative_prompt: str
    ) -> GenerationResult:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            image_bytes = reference_image_path.read_bytes()

            full_prompt = prompt
            if negative_prompt:
                full_prompt += f". Avoid: {negative_prompt}"

            response = client.models.generate_content(
                model=self.MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=full_prompt),
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return GenerationResult(
                        success=True,
                        image_data=part.inline_data.data,
                    )

            return GenerationResult(success=False, error="응답에 이미지가 없습니다.")

        except Exception as e:
            return GenerationResult(success=False, error=str(e))


def get_provider(provider_name: str = None) -> BaseImageProvider:
    """provider 이름으로 인스턴스 반환"""
    name = provider_name or settings.default_provider
    if name == "openai":
        return OpenAIProvider()
    elif name == "stability":
        return StabilityProvider()
    elif name == "gemini":
        return GeminiProvider()
    else:
        raise ValueError(f"지원하지 않는 provider: '{name}'. 사용 가능: openai, stability, gemini")
