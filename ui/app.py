# 스마트스토어 대표이미지 자동 생성 - Streamlit UI
# 실행: streamlit run ui/app.py

import asyncio
import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

# 프로젝트 루트를 sys.path 맨 앞에 강제 삽입
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

import streamlit as st
from PIL import Image

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.image_preprocess import ImagePreprocessor
from app.services.preset_manager import PresetManager
from app.services.provider_client import get_provider
from app.services.batch_runner import BatchRunner
from app.services.ranker import ImageRanker
from app.services.exporter import Exporter
from app.schemas.prompt_preset import PresetCollection, PromptPreset, VariationSchema
from app.config import settings

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(
    page_title="스마트스토어 대표이미지 생성기",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.top-badge {
    background: linear-gradient(90deg, #FFD700, #FFA500);
    color: #000; padding: 2px 10px;
    border-radius: 12px; font-size: 12px; font-weight: bold;
}
.rank-badge {
    background: #1e90ff; color: #fff;
    padding: 2px 8px; border-radius: 10px; font-size: 12px;
}
.score-text { color: #00cc66; font-weight: bold; font-size: 14px; }
div[data-testid="stImage"] img { border-radius: 8px; border: 1px solid #e0e0e0; }
.preset-box {
    border: 1px solid #ddd; border-radius: 8px;
    padding: 12px; margin-bottom: 8px; background: #fafafa;
}
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 초기화 ───────────────────────────────────────────
for key, default in {
    "job": None, "generated": False, "processed_path": None,
    "page": "generate",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def get_manager():
    return PresetManager(presets_dir=ROOT / "presets")


# ══════════════════════════════════════════════════════════════
#  사이드바 — 페이지 전환
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("🛍️ 대표이미지 생성기")
    st.markdown("---")

    page = st.radio(
        "메뉴",
        options=["generate", "preset"],
        format_func=lambda x: "🚀 이미지 생성" if x == "generate" else "🎨 프리셋 관리",
        key="page",
        label_visibility="collapsed",
    )
    st.markdown("---")


# ══════════════════════════════════════════════════════════════
#  페이지 1: 이미지 생성
# ══════════════════════════════════════════════════════════════
if st.session_state.page == "generate":

    with st.sidebar:
        st.subheader("📁 1. 누끼 이미지 업로드")
        uploaded_file = st.file_uploader(
            "PNG 파일 (투명 배경 권장)",
            type=["png", "jpg", "jpeg"],
        )
        if uploaded_file:
            preview_img = Image.open(uploaded_file)
            st.image(preview_img, caption="업로드된 이미지", use_container_width=True)
            st.caption(f"{preview_img.width}×{preview_img.height}px")
            uploaded_file.seek(0)

        st.markdown("---")
        st.subheader("📝 2. 상품 설명")
        product_desc = st.text_input(
            "상품명 / 설명",
            placeholder="예: 스킨케어 세럼 50ml",
            help="프롬프트의 {product} 자리에 삽입됩니다.",
        )

        st.markdown("---")
        st.subheader("🎨 3. 프리셋")
        manager = get_manager()
        collection_ids = manager.list_collections()

        if not collection_ids:
            st.warning("프리셋이 없습니다. 프리셋 관리에서 먼저 만드세요.")
            preset_id = None
        else:
            preset_id = st.selectbox(
                "프리셋 컬렉션",
                options=collection_ids,
                format_func=lambda x: manager.get_collection(x).name if manager.get_collection(x) else x,
            )
            if preset_id:
                col_obj = manager.get_collection(preset_id)
                with st.expander("프리셋 목록 보기"):
                    for p in col_obj.presets:
                        st.markdown(f"**{p.name}** `weight:{p.weight}`")
                        st.caption(p.description)

        st.markdown("---")
        st.subheader("⚙️ 4. 생성 설정")
        count = st.slider("생성 수량", 5, 30, 20)
        top_n = st.slider("상위 선별 수", 3, 10, 5)
        provider_name = st.selectbox("Provider", ["openai", "stability"])

        st.markdown("---")
        can_generate = bool(uploaded_file and product_desc and preset_id)
        generate_btn = st.button(
            "🚀 대표이미지 생성 시작",
            type="primary",
            use_container_width=True,
            disabled=not can_generate,
        )
        if not uploaded_file:
            st.caption("⬆️ 이미지를 먼저 업로드하세요.")
        elif not product_desc:
            st.caption("⬆️ 상품 설명을 입력하세요.")

    # ── 메인 영역
    st.title("🛍️ 스마트스토어 대표이미지 자동 생성")

    if not can_generate:
        st.markdown("### 👈 왼쪽 패널에서 이미지와 상품 설명을 입력하세요.")
        st.markdown("""
| 슬롯 | 기본 프리셋 | 특징 |
|---|---|---|
| 1 | 화이트 배경 기본형 | 가장 범용, 스마트스토어 기본 기준 |
| 2 | 소프트 그림자형 | 자연 그림자로 입체감 |
| 3 | 프리미엄 미니멀형 | 넓은 여백, 고급 브랜드 톤 |
| 4 | 감성 배경 최소형 | 텍스처 배경, 따뜻한 무드 |
| 5 | 디스플레이 스탠드형 | 받침대 연출, 카탈로그 스타일 |
        """)
        st.stop()

    if generate_btn:
        st.session_state.generated = False
        st.session_state.job = None
        collection = manager.get_collection(preset_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / uploaded_file.name
            tmp_path.write_bytes(uploaded_file.read())

            status_box = st.empty()
            status_box.info("📐 이미지 전처리 중...")
            preprocessor = ImagePreprocessor(canvas_size=settings.canvas_size)
            try:
                product_img = preprocessor.load_and_validate(tmp_path)
            except Exception as e:
                st.error(f"이미지 오류: {e}")
                st.stop()

            processed_dir = settings.output_dir / "_preprocessed"
            processed = preprocessor.preprocess(product_img, processed_dir)

            status_box.info(f"🎨 이미지 생성 중... (총 {count}장)")
            progress_bar = st.progress(0, text="생성 준비 중...")

            try:
                provider = get_provider(provider_name)
            except ValueError as e:
                st.error(str(e))
                st.stop()

            runner = BatchRunner(provider=provider)
            job = runner.create_job(processed, collection, product_desc, total_count=count)

            completed_count = [0]
            total = len(job.tasks)

            async def run_with_progress():
                from app.schemas.job import JobStatus
                from datetime import datetime
                semaphore = asyncio.Semaphore(settings.max_workers)
                images_dir = job.output_dir / "images"
                images_dir.mkdir(parents=True, exist_ok=True)

                async def run_single(task):
                    async with semaphore:
                        result = await provider.generate(
                            prompt=task.prompt,
                            reference_image_path=job.product_image_path,
                            negative_prompt=collection.global_negative_prompt,
                        )
                        if result.success:
                            out_path = images_dir / f"{task.task_id}_{task.preset_id}.png"
                            out_path.write_bytes(result.image_data)
                            task.output_path = out_path
                            task.status = JobStatus.COMPLETED
                            task.completed_at = datetime.now()
                        else:
                            task.status = JobStatus.FAILED
                            task.error = result.error
                        completed_count[0] += 1
                        progress_bar.progress(
                            completed_count[0] / total,
                            text=f"생성 중... {completed_count[0]}/{total}장",
                        )
                await asyncio.gather(*[run_single(t) for t in job.tasks])

            asyncio.run(run_with_progress())

            from app.schemas.job import JobStatus
            from datetime import datetime
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            runner._save_job_meta(job)

            progress_bar.progress(1.0, text="상위 이미지 선별 중...")
            ranker = ImageRanker()
            job = ranker.rank_job(job, top_n=top_n)
            Exporter().export(job)

            status_box.success(f"✅ 완료! {len(job.completed_tasks)}장 생성, 상위 {top_n}장 선별")
            progress_bar.empty()
            st.session_state.job = job
            st.session_state.generated = True

    # ── 결과 출력
    if st.session_state.generated and st.session_state.job:
        job = st.session_state.job
        top_ids = set(job.top_results)
        completed = job.completed_tasks
        ranked = sorted(completed, key=lambda t: t.score or 0.0, reverse=True)

        tab_top, tab_all, tab_log = st.tabs([
            f"⭐ 상위 {len(job.top_results)}장",
            f"📋 전체 {len(completed)}장",
            "📄 프롬프트 로그",
        ])

        with tab_top:
            st.markdown(f"### ⭐ 상위 {len(job.top_results)}장")
            top_tasks = [t for t in ranked if t.task_id in top_ids]
            cols = st.columns(min(len(top_tasks), 3))
            for i, task in enumerate(top_tasks):
                with cols[i % len(cols)]:
                    if task.output_path and Path(task.output_path).exists():
                        img = Image.open(task.output_path)
                        st.image(img, use_container_width=True)
                        st.markdown(
                            f'<span class="top-badge">★ #{i+1}</span> '
                            f'<span class="score-text">{task.score:.3f}</span>',
                            unsafe_allow_html=True,
                        )
                        st.caption(task.preset_id)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        st.download_button(
                            "💾 다운로드", buf.getvalue(),
                            f"rank{i+1:02d}_{task.preset_id}.png", "image/png",
                            key=f"dl_top_{task.task_id}", use_container_width=True,
                        )
            st.markdown("---")
            zip_path = Exporter().create_zip(job)
            if zip_path.exists():
                st.download_button(
                    "📦 전체 결과 ZIP 다운로드", zip_path.read_bytes(),
                    f"{job.job_id}_results.zip", "application/zip",
                    use_container_width=True,
                )

        with tab_all:
            st.markdown(f"### 📋 전체 {len(completed)}장")
            cols_per_row = 4
            for row_start in range(0, len(ranked), cols_per_row):
                cols = st.columns(cols_per_row)
                for col, task in zip(cols, ranked[row_start:row_start + cols_per_row]):
                    if task.output_path and Path(task.output_path).exists():
                        rank = ranked.index(task) + 1
                        with col:
                            img = Image.open(task.output_path)
                            st.image(img, use_container_width=True)
                            badge = (f'<span class="top-badge">★#{rank}</span>'
                                     if task.task_id in top_ids
                                     else f'<span class="rank-badge">#{rank}</span>')
                            st.markdown(
                                f'{badge} <span class="score-text">{task.score:.3f}</span>',
                                unsafe_allow_html=True,
                            )
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            st.download_button(
                                "💾", buf.getvalue(),
                                f"rank{rank:02d}_{task.task_id}.png", "image/png",
                                key=f"dl_all_{task.task_id}", use_container_width=True,
                            )

        with tab_log:
            st.markdown(f"**Job ID:** `{job.job_id}`")
            import pandas as pd
            log_data = [{
                "순위": i + 1,
                "★": "★" if t.task_id in top_ids else "",
                "프리셋": t.preset_id,
                "점수": f"{t.score:.4f}" if t.score else "-",
                "배경": t.variation.get("background", ""),
                "그림자": t.variation.get("shadow", ""),
                "각도": t.variation.get("angle", ""),
                "여백": t.variation.get("spacing", ""),
                "소품": t.variation.get("prop", ""),
            } for i, t in enumerate(ranked)]
            st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)
            for task in ranked[:top_n]:
                with st.expander(f"#{ranked.index(task)+1} [{task.preset_id}] {task.score:.3f}"):
                    st.code(task.prompt)


# ══════════════════════════════════════════════════════════════
#  페이지 2: 프리셋 관리
# ══════════════════════════════════════════════════════════════
elif st.session_state.page == "preset":

    st.title("🎨 프리셋 컬렉션 관리")
    st.caption("프롬프트 프리셋을 만들고 저장해 이미지 생성에 바로 반영하세요.")

    manager = get_manager()
    collection_ids = manager.list_collections()
    presets_dir = ROOT / "presets"

    # ── 상단: 컬렉션 선택 or 새로 만들기
    col_select, col_new = st.columns([3, 1])
    with col_select:
        options = ["✨ 새 컬렉션 만들기"] + collection_ids
        selected = st.selectbox(
            "컬렉션 선택",
            options=options,
            format_func=lambda x: x if x == "✨ 새 컬렉션 만들기"
            else f"{manager.get_collection(x).name} ({x})" if manager.get_collection(x) else x,
        )

    is_new = selected == "✨ 새 컬렉션 만들기"

    # ── 기존 컬렉션 로드 or 빈 상태
    if is_new:
        init_col = PresetCollection(
            id="", name="", category="smartstore",
            presets=[], global_negative_prompt="",
        )
    else:
        init_col = manager.get_collection(selected)

    st.markdown("---")

    # ── 컬렉션 기본 정보
    st.subheader("📋 컬렉션 기본 정보")
    info_c1, info_c2 = st.columns(2)
    with info_c1:
        col_id = st.text_input(
            "컬렉션 ID (영문, 저장 파일명)",
            value="" if is_new else init_col.id,
            placeholder="예: my_cosmetics",
            disabled=not is_new,
        )
        col_name = st.text_input(
            "컬렉션 이름",
            value=init_col.name,
            placeholder="예: 화장품 기본 세트",
        )
    with info_c2:
        col_category = st.text_input(
            "카테고리",
            value=init_col.category,
            placeholder="예: smartstore, fashion, food",
        )
        col_negative = st.text_area(
            "글로벌 네거티브 프롬프트",
            value=init_col.global_negative_prompt,
            height=80,
            placeholder="생성 시 제외할 요소 (쉼표 구분)",
        )

    st.markdown("---")

    # ── 프리셋 슬롯 편집
    st.subheader("🗂️ 프리셋 슬롯 (최대 5개)")
    st.caption("`{product}` 는 생성 시 상품 설명으로 자동 치환됩니다. Variation 항목은 쉼표로 구분해서 입력하세요.")

    # 세션에서 임시 프리셋 목록 관리
    sess_key = f"preset_slots_{selected}"
    if sess_key not in st.session_state or st.session_state.get(f"_sess_src_{sess_key}") != selected:
        st.session_state[sess_key] = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "template": p.template,
                "weight": p.weight,
                "background": ", ".join(p.variation_schema.background),
                "shadow": ", ".join(p.variation_schema.shadow),
                "angle": ", ".join(p.variation_schema.angle),
                "spacing": ", ".join(p.variation_schema.spacing),
                "prop": ", ".join(p.variation_schema.prop),
            }
            for p in init_col.presets
        ]
        st.session_state[f"_sess_src_{sess_key}"] = selected

    slots = st.session_state[sess_key]

    # 슬롯 추가 버튼
    if len(slots) < 5:
        if st.button("➕ 프리셋 슬롯 추가", use_container_width=False):
            idx = len(slots) + 1
            slots.append({
                "id": f"preset_{idx:02d}_new",
                "name": f"새 프리셋 {idx}",
                "description": "",
                "template": "Professional product photography of {product} on a {background} background, {shadow} shadow, {angle}, {spacing} composition, {prop}",
                "weight": 1.0,
                "background": "white, light gray, beige",
                "shadow": "none, soft, natural",
                "angle": "front view, 3/4 view",
                "spacing": "normal, wide",
                "prop": "none, minimal",
            })
            st.rerun()

    # 각 슬롯 렌더링
    for i, slot in enumerate(slots):
        with st.expander(f"**슬롯 {i+1}: {slot['name']}**", expanded=(i == 0 and is_new)):
            top_cols = st.columns([3, 1, 1])
            with top_cols[0]:
                slot["name"] = st.text_input(
                    "프리셋 이름", value=slot["name"], key=f"name_{sess_key}_{i}"
                )
            with top_cols[1]:
                slot["id"] = st.text_input(
                    "ID", value=slot["id"], key=f"id_{sess_key}_{i}"
                )
            with top_cols[2]:
                slot["weight"] = st.number_input(
                    "Weight", value=float(slot["weight"]),
                    min_value=0.1, max_value=3.0, step=0.1,
                    key=f"weight_{sess_key}_{i}",
                )

            slot["description"] = st.text_input(
                "설명", value=slot["description"], key=f"desc_{sess_key}_{i}",
                placeholder="이 프리셋의 스타일 설명"
            )

            slot["template"] = st.text_area(
                "프롬프트 템플릿",
                value=slot["template"],
                height=100,
                key=f"tmpl_{sess_key}_{i}",
                help="{product} {background} {shadow} {angle} {spacing} {prop} 변수 사용 가능",
            )

            st.markdown("**Variation 파라미터** (쉼표로 구분, 조합하여 다양성 생성)")
            v1, v2, v3 = st.columns(3)
            v4, v5 = st.columns(2)
            with v1:
                slot["background"] = st.text_input(
                    "배경 (background)", value=slot["background"], key=f"bg_{sess_key}_{i}",
                    placeholder="white, light gray, beige"
                )
            with v2:
                slot["shadow"] = st.text_input(
                    "그림자 (shadow)", value=slot["shadow"], key=f"sh_{sess_key}_{i}",
                    placeholder="none, soft, natural"
                )
            with v3:
                slot["angle"] = st.text_input(
                    "각도 (angle)", value=slot["angle"], key=f"an_{sess_key}_{i}",
                    placeholder="front view, 3/4 view"
                )
            with v4:
                slot["spacing"] = st.text_input(
                    "여백 (spacing)", value=slot["spacing"], key=f"sp_{sess_key}_{i}",
                    placeholder="normal, wide"
                )
            with v5:
                slot["prop"] = st.text_input(
                    "소품 (prop)", value=slot["prop"], key=f"pr_{sess_key}_{i}",
                    placeholder="none, minimal"
                )

            if st.button(f"🗑️ 이 슬롯 삭제", key=f"del_{sess_key}_{i}", type="secondary"):
                slots.pop(i)
                st.rerun()

    # ── 저장 버튼
    st.markdown("---")
    save_col, del_col = st.columns([4, 1])

    with save_col:
        if st.button("💾 컬렉션 저장", type="primary", use_container_width=True):
            errors = []
            if not col_id.strip():
                errors.append("컬렉션 ID를 입력하세요.")
            if not col_name.strip():
                errors.append("컬렉션 이름을 입력하세요.")
            if not slots:
                errors.append("프리셋 슬롯이 최소 1개 필요합니다.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                def _parse_list(text: str):
                    return [x.strip() for x in text.split(",") if x.strip()] or ["none"]

                presets = []
                for slot in slots:
                    presets.append(PromptPreset(
                        id=slot["id"].strip(),
                        name=slot["name"].strip(),
                        description=slot["description"].strip(),
                        template=slot["template"].strip(),
                        weight=float(slot["weight"]),
                        variation_schema=VariationSchema(
                            background=_parse_list(slot["background"]),
                            shadow=_parse_list(slot["shadow"]),
                            angle=_parse_list(slot["angle"]),
                            spacing=_parse_list(slot["spacing"]),
                            prop=_parse_list(slot["prop"]),
                        ),
                    ))

                new_collection = PresetCollection(
                    id=col_id.strip(),
                    name=col_name.strip(),
                    category=col_category.strip() or "smartstore",
                    global_negative_prompt=col_negative.strip(),
                    presets=presets,
                )

                save_path = presets_dir / f"{col_id.strip()}.json"
                manager.save_collection(new_collection, save_path)

                # 세션 캐시 초기화
                for k in list(st.session_state.keys()):
                    if k.startswith("preset_slots_") or k.startswith("_sess_src_"):
                        del st.session_state[k]

                st.success(f"✅ 저장 완료! `presets/{col_id.strip()}.json`")
                st.balloons()

    with del_col:
        if not is_new:
            if st.button("🗑️ 삭제", type="secondary", use_container_width=True):
                json_file = presets_dir / f"{selected}.json"
                if json_file.exists():
                    json_file.unlink()
                    for k in list(st.session_state.keys()):
                        if k.startswith("preset_slots_") or k.startswith("_sess_src_"):
                            del st.session_state[k]
                    st.warning(f"삭제됨: {selected}")
                    st.rerun()

    # ── 현재 저장된 프리셋 JSON 미리보기
    if not is_new and init_col:
        with st.expander("📄 JSON 미리보기"):
            st.json(init_col.model_dump())
