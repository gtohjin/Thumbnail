"""
Image Ranker: 생성된 이미지의 스마트스토어 대표이미지 적합도 평가

평가 기준 (가중치):
  1. 상품 식별력 (0.35) — 엣지 밀도 기반 상품 존재감
  2. 중심성      (0.25) — 상품 무게중심의 화면 중앙 근접도
  3. 배경 단순성 (0.25) — 가장자리 배경 영역의 색 분산
  4. 적절한 크기 (0.15) — 전체 이미지 밝기 표준편차

중복 제거: perceptual hash (pHash) 거리 기반
"""

from pathlib import Path
from typing import List

import imagehash
import numpy as np
from PIL import Image, ImageFilter

from app.schemas.job import GenerationTask, Job, JobStatus


class ImageRanker:
    def __init__(self, hash_threshold: int = 10):
        # pHash 해밍거리 임계값 (낮을수록 엄격하게 중복 판정)
        self.hash_threshold = hash_threshold

    def score_task(self, task: GenerationTask) -> float:
        """단일 태스크 적합도 점수 계산 (0.0 ~ 1.0)"""
        if task.status != JobStatus.COMPLETED or task.output_path is None:
            return 0.0
        if not Path(task.output_path).exists():
            return 0.0

        try:
            with Image.open(task.output_path) as img:
                img_rgb = img.convert("RGB")
                scores = {
                    "product_visibility": self._score_product_visibility(img_rgb),
                    "centering": self._score_centering(img_rgb),
                    "background_simplicity": self._score_background_simplicity(img_rgb),
                    "size_appropriateness": self._score_size_appropriateness(img_rgb),
                }
                weights = {
                    "product_visibility": 0.35,
                    "centering": 0.25,
                    "background_simplicity": 0.25,
                    "size_appropriateness": 0.15,
                }
                return round(sum(scores[k] * weights[k] for k in scores), 4)
        except Exception:
            return 0.0

    def rank_job(self, job: Job, top_n: int = 5, deduplicate: bool = True) -> Job:
        """Job 내 완료 태스크 전체 점수화 → 중복 제거 → 상위 N개 선별"""
        completed = job.completed_tasks

        for task in completed:
            task.score = self.score_task(task)

        ranked = sorted(completed, key=lambda t: t.score or 0.0, reverse=True)

        if deduplicate:
            ranked = self._deduplicate(ranked)

        top = ranked[:top_n]
        job.top_results = [t.task_id for t in top]
        return job

    # ── 개별 평가 함수 ─────────────────────────────────────────

    def _score_product_visibility(self, img: Image.Image) -> float:
        """엣지 밀도로 상품 식별성 추정.
        엣지가 너무 적으면 상품 없음, 너무 많으면 배경 복잡."""
        edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
        arr = np.array(edges)
        edge_ratio = float((arr > 30).sum()) / arr.size

        if edge_ratio < 0.02:
            return 0.2
        elif edge_ratio < 0.06:
            return 0.7
        elif edge_ratio < 0.20:
            return 1.0
        elif edge_ratio < 0.35:
            return 0.65
        else:
            return 0.3

    def _score_centering(self, img: Image.Image) -> float:
        """상품(어두운 영역) 무게중심이 화면 중앙에 얼마나 가까운지.
        배경이 밝고 상품이 어두운 일반적인 스튜디오 구성 가정."""
        arr = np.array(img.convert("L"))
        threshold = float(np.percentile(arr, 70))
        mask = arr < threshold

        if mask.sum() == 0:
            return 0.5

        rows, cols = np.where(mask)
        cy = rows.mean() / arr.shape[0]
        cx = cols.mean() / arr.shape[1]

        dist = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
        return max(0.0, 1.0 - dist * 2.0)

    def _score_background_simplicity(self, img: Image.Image) -> float:
        """가장자리 15% 영역을 배경으로 간주, 색 분산이 낮을수록 단순."""
        arr = np.array(img).astype(float)
        h, w = arr.shape[:2]
        margin = max(1, int(min(h, w) * 0.15))

        background = np.concatenate([
            arr[:margin, :].reshape(-1, 3),
            arr[-margin:, :].reshape(-1, 3),
            arr[:, :margin].reshape(-1, 3),
            arr[:, -margin:].reshape(-1, 3),
        ])

        if len(background) == 0:
            return 0.5

        variance = float(background.var(axis=0).mean())

        if variance < 100:
            return 1.0
        elif variance < 500:
            return 0.8
        elif variance < 2000:
            return 0.5
        else:
            return 0.2

    def _score_size_appropriateness(self, img: Image.Image) -> float:
        """밝기 표준편차 기반으로 콘텐츠 적절성 추정."""
        arr = np.array(img.convert("L")).astype(float)
        std = float(arr.std())

        if std < 10:
            return 0.3
        elif std < 30:
            return 0.7
        elif std < 80:
            return 1.0
        else:
            return 0.5

    def _deduplicate(self, tasks: List[GenerationTask]) -> List[GenerationTask]:
        """pHash 기반 중복 이미지 제거. 점수 높은 순으로 이미 정렬된 상태 가정."""
        selected: List[GenerationTask] = []
        hashes = []

        for task in tasks:
            if task.output_path is None or not Path(task.output_path).exists():
                continue
            try:
                with Image.open(task.output_path) as img:
                    h = imagehash.phash(img)
                if any(abs(h - existing) < self.hash_threshold for existing in hashes):
                    continue
                selected.append(task)
                hashes.append(h)
            except Exception:
                selected.append(task)

        return selected
