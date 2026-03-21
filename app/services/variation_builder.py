import itertools
import random
from typing import Dict, List, Tuple

from app.schemas.prompt_preset import PresetCollection, PromptPreset


class VariationBuilder:
    """
    프리셋 컬렉션에서 총 N개의 (preset, variation, prompt) 조합 생성.
    - 각 프리셋의 weight 비율에 따라 개수 할당
    - variation은 조합 수 내에서 다양성 최대화 샘플링
    - 총합이 정확히 total_count가 되도록 보정
    """

    def __init__(self, seed: int = None):
        self.rng = random.Random(seed)

    def build_variations(
        self, collection: PresetCollection, total_count: int = 20
    ) -> List[Tuple[PromptPreset, Dict[str, str], str]]:
        """
        Returns: List of (PromptPreset, variation_dict, rendered_prompt_template)
        - rendered_prompt_template은 {product} 자리가 아직 비어있음
        - finalize_prompt()로 상품 설명 삽입 필요
        """
        presets = collection.presets
        allocations = self._allocate_counts(presets, total_count)

        results = []
        for preset, count in zip(presets, allocations):
            variations = self._sample_variations(preset, count)
            for var in variations:
                prompt = self._render_template(preset.template, var)
                results.append((preset, var, prompt))

        # 정확히 total_count 맞추기
        while len(results) < total_count:
            preset = self.rng.choice(presets)
            var = self._sample_single_variation(preset)
            prompt = self._render_template(preset.template, var)
            results.append((preset, var, prompt))
        results = results[:total_count]

        self.rng.shuffle(results)
        return results

    def finalize_prompt(self, prompt: str, product_description: str) -> str:
        """{product} 자리에 실제 상품 설명 삽입"""
        return prompt.replace("{product}", product_description)

    def _allocate_counts(self, presets: List[PromptPreset], total: int) -> List[int]:
        """가중치 기반으로 각 프리셋에 할당할 생성 수 계산"""
        total_weight = sum(p.weight for p in presets)
        allocations = []
        remaining = total

        for i, preset in enumerate(presets):
            if i == len(presets) - 1:
                allocations.append(remaining)
            else:
                count = max(1, round(total * preset.weight / total_weight))
                count = min(count, remaining - (len(presets) - i - 1))
                allocations.append(count)
                remaining -= count

        return allocations

    def _sample_variations(self, preset: PromptPreset, count: int) -> List[Dict[str, str]]:
        """variation 조합에서 count개 샘플링 (다양성 우선)"""
        schema_dict = preset.variation_schema.model_dump()
        keys = list(schema_dict.keys())
        all_combos = list(itertools.product(*[schema_dict[k] for k in keys]))

        if not all_combos:
            return [{}] * count

        if len(all_combos) <= count:
            # 조합 수 < 요청 수: 반복 허용
            samples = (all_combos * (count // len(all_combos) + 1))[:count]
        else:
            samples = self.rng.sample(all_combos, count)

        return [dict(zip(keys, combo)) for combo in samples]

    def _sample_single_variation(self, preset: PromptPreset) -> Dict[str, str]:
        """단일 variation 랜덤 샘플"""
        schema_dict = preset.variation_schema.model_dump()
        return {k: self.rng.choice(v) for k, v in schema_dict.items()}

    def _render_template(self, template: str, variation: Dict[str, str]) -> str:
        """템플릿에 variation 값 치환 ({product}는 유지)"""
        result = template
        for key, value in variation.items():
            result = result.replace(f"{{{key}}}", value)
        return result
