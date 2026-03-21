# CLAUDE.md — 스마트스토어 대표이미지 자동 생성 시스템

## 프로젝트 개요

누끼 처리된 상품 PNG를 참조 이미지로 사용하여
고정 프롬프트 프리셋 5개 × variation 조합으로
스마트스토어 대표이미지 후보 20장을 일괄 생성하는 배치 파이프라인.

**핵심 원칙**
- "텍스트 무작위 생성기"가 아닌 "참조 이미지 기반 대표이미지 생성기"
- 프롬프트는 고정 프리셋 5개 슬롯. 매번 새로 만들지 않는다
- 다양성은 variation 파라미터 조합으로 만든다 (배경·그림자·각도·여백·소품)
- 대표이미지는 예쁨보다 식별성 우선

---

## 폴더 구조

```
smartstore-ref-image-generator/
├─ app/
│  ├─ main.py                 # CLI 진입점
│  ├─ config.py               # pydantic-settings 기반 환경 설정
│  ├─ schemas/
│  │  ├─ product_image.py     # ProductImage, ProcessedImage
│  │  ├─ prompt_preset.py     # VariationSchema, PromptPreset, PresetCollection
│  │  └─ job.py               # GenerationTask, Job, JobStatus
│  ├─ services/
│  │  ├─ image_preprocess.py  # 누끼 이미지 전처리 (정사각형 캔버스)
│  │  ├─ preset_manager.py    # JSON 프리셋 로드/저장
│  │  ├─ provider_client.py   # Provider 추상화 (OpenAI / Stability)
│  │  ├─ variation_builder.py # variation 조합 생성 + 프롬프트 렌더링
│  │  ├─ batch_runner.py      # 비동기 병렬 생성 실행
│  │  ├─ ranker.py            # 이미지 적합도 점수화 + 중복 제거
│  │  └─ exporter.py          # 결과 정리 (top images, JSON 로그, CSV, ZIP)
│  ├─ cli/
│  │  └─ commands.py          # Click CLI 명령어
│  └─ utils/
│     └─ logger.py
├─ presets/
│  ├─ smartstore_default.json # 기본 5개 프리셋
│  └─ category/               # 카테고리별 프리셋 (확장용)
├─ outputs/                   # 생성 결과 (job_YYYYMMDD_HHMMSS_xxxx/)
├─ tests/
│  └─ test_basic.py
├─ .env                       # API 키 등 (gitignore)
├─ .env.example
├─ requirements.txt
└─ README.md
```

---

## 핵심 모듈 설명

### provider_client.py
- `BaseImageProvider` 추상 클래스 → `generate(prompt, reference_image_path, negative_prompt)`
- `OpenAIProvider`: DALL-E 2 images/edits 엔드포인트
- `StabilityProvider`: SDXL img2img 엔드포인트
- `get_provider(name)`: 이름으로 provider 반환
- **새 provider 추가**: `BaseImageProvider` 상속 후 `get_provider()`에 등록

### variation_builder.py
- `build_variations(collection, total_count=20)` → `List[(preset, var_dict, prompt_template)]`
- 프리셋 weight 비율에 따라 total_count 할당
- variation schema 조합 수 < count이면 반복 허용
- `{product}` 자리는 `finalize_prompt()`로 나중에 치환

### batch_runner.py
- `create_job()`: variation 기반 GenerationTask 목록 생성 + job_meta.json 저장
- `run()`: asyncio + Semaphore(MAX_WORKERS) 병렬 실행
- `retry_failed()`: 실패 태스크만 PENDING 리셋 후 재실행
- `load_job(job_id)`: outputs/{job_id}/job_meta.json 에서 복원

### ranker.py
평가 기준 (가중치):
1. 상품 식별력 0.35 — 엣지 밀도
2. 중심성 0.25 — 상품 무게중심의 중앙 근접도
3. 배경 단순성 0.25 — 가장자리 영역 색 분산
4. 크기 적절성 0.15 — 밝기 표준편차

pHash 해밍거리 < 10이면 중복으로 제거.

---

## CLI 사용법

```bash
# 환경 설정
cp .env.example .env
# .env에 OPENAI_API_KEY 또는 STABILITY_API_KEY 입력

# 패키지 설치
pip install -r requirements.txt

# 이미지 생성 (기본 20장)
python -m app.main generate \
  --image path/to/product_nukki.png \
  --product "스킨케어 세럼 50ml" \
  --preset smartstore_default \
  --count 20 \
  --top 5

# 재평가
python -m app.main rerank job_20240101_120000_ab12

# 내보내기 (ZIP 포함)
python -m app.main export job_20240101_120000_ab12 --zip

# 목록 조회
python -m app.main list-jobs
python -m app.main list-presets
```

---

## 프리셋 구조 (smartstore_default.json)

| 슬롯 | ID | 이름 | 특징 |
|---|---|---|---|
| 1 | preset_01_white_basic | 화이트 배경 기본형 | 가장 범용, weight 1.2 |
| 2 | preset_02_soft_shadow | 소프트 그림자형 | 입체감 강조 |
| 3 | preset_03_premium_minimal | 프리미엄 미니멀형 | 넓은 여백, 고급감 |
| 4 | preset_04_lifestyle_minimal | 감성 배경 최소형 | 텍스처 배경, 따뜻한 톤 |
| 5 | preset_05_display_stand | 디스플레이 스탠드형 | 받침대 연출, 카탈로그 스타일 |

각 프리셋은 `variation_schema` (background, shadow, angle, spacing, prop) 보유.

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| OPENAI_API_KEY | OpenAI API 키 | — |
| STABILITY_API_KEY | Stability AI API 키 | — |
| DEFAULT_PROVIDER | 기본 provider | openai |
| OUTPUT_DIR | 결과 저장 폴더 | outputs |
| CANVAS_SIZE | 정사각형 캔버스 크기 | 1024 |
| MAX_WORKERS | 병렬 생성 worker 수 | 4 |

---

## 출력 구조

```
outputs/
└─ job_20240101_120000_ab12/
   ├─ job_meta.json          # Job 전체 메타 + 태스크 목록
   ├─ images/                # 생성된 이미지 전체 (20장)
   │  ├─ t_abc123_preset_01_white_basic.png
   │  └─ ...
   └─ export/
      ├─ top_results/        # 상위 5장 (rank01~05_...)
      ├─ prompt_log.json     # 프롬프트·variation·점수 전체 로그
      └─ results_summary.csv # 랭킹 요약
```

---

## 주요 설계 결정

- **provider abstraction**: API 변경 시 `BaseImageProvider` 구현체만 교체
- **variation 기반 다양성**: 프롬프트 무한 생성 대신 파라미터 조합으로 일관성 유지
- **pHash 중복 제거**: 비슷한 결과가 상위에 몰리는 것 방지
- **job_meta.json 저장**: 실행 중단 시 `retry_failed()` 로 재개 가능
- **스마트스토어 최적화**: 1024×1024 정사각형, 식별성·중심성 우선 랭킹
