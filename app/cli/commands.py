"""
CLI Commands

사용법:
  python -m app.main generate --image product.png --product "스킨로션 100ml" --preset smartstore_default
  python -m app.main rerank job_20240101_120000_ab12
  python -m app.main export job_20240101_120000_ab12 --zip
  python -m app.main list-jobs
  python -m app.main list-presets
"""

import asyncio
import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from app.config import settings
from app.services.batch_runner import BatchRunner
from app.services.exporter import Exporter
from app.services.image_preprocess import ImagePreprocessor
from app.services.preset_manager import PresetManager
from app.services.provider_client import get_provider
from app.services.ranker import ImageRanker

console = Console()


@click.group()
def cli():
    """스마트스토어 대표이미지 자동 생성 시스템"""
    pass


@cli.command()
@click.option("--image", required=True, type=click.Path(exists=True), help="누끼 PNG 이미지 경로")
@click.option("--preset", default="smartstore_default", show_default=True, help="프리셋 컬렉션 ID")
@click.option("--count", default=20, show_default=True, type=int, help="생성할 이미지 수")
@click.option("--product", default="product", show_default=True, help="상품 설명 (프롬프트 {product} 치환)")
@click.option("--provider", default=None, help="이미지 생성 provider (openai / stability)")
@click.option("--top", default=5, show_default=True, type=int, help="자동 선별할 상위 이미지 수")
def generate(image, preset, count, product, provider, top):
    """누끼 이미지를 기반으로 스마트스토어 대표이미지 생성"""

    # 1. 이미지 전처리
    console.rule("[bold cyan]1. 이미지 전처리[/bold cyan]")
    preprocessor = ImagePreprocessor()
    image_path = Path(image)

    try:
        product_img = preprocessor.load_and_validate(image_path)
    except Exception as e:
        console.print(f"[red]이미지 로드 실패: {e}[/red]")
        raise SystemExit(1)

    console.print(f"  입력: [bold]{product_img.name}[/bold] ({product_img.width}×{product_img.height})")
    if not product_img.has_alpha:
        console.print("  [yellow]⚠ 알파 채널 없음 — 누끼 처리된 RGBA PNG를 사용하면 더 정확합니다.[/yellow]")

    temp_dir = settings.output_dir / "_preprocessed"
    processed = preprocessor.preprocess(product_img, temp_dir)
    console.print(f"  전처리 완료: {processed.canvas_size}×{processed.canvas_size}px → {processed.path}")

    # 2. 프리셋 로드
    console.rule(f"[bold cyan]2. 프리셋 로드[/bold cyan]")
    manager = PresetManager()
    collection = manager.get_collection(preset)

    if not collection:
        console.print(f"[red]프리셋 '{preset}' 없음.[/red]")
        console.print(f"  사용 가능한 프리셋: {manager.list_collections()}")
        raise SystemExit(1)

    console.print(f"  [bold]{collection.name}[/bold] — 프리셋 {len(collection.presets)}개")
    for p in collection.presets:
        console.print(f"  · [{p.id}] {p.name} (weight={p.weight})")

    # 3. Job 생성 및 실행
    console.rule(f"[bold cyan]3. 배치 생성 ({count}장)[/bold cyan]")
    try:
        _provider = get_provider(provider)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    runner = BatchRunner(provider=_provider)
    job = runner.create_job(processed, collection, product, total_count=count)
    console.print(f"  Job ID: [bold]{job.job_id}[/bold]")
    console.print(f"  출력 폴더: {job.output_dir}")

    job = asyncio.run(runner.run(job, negative_prompt=collection.global_negative_prompt))

    # 4. 랭킹
    console.rule("[bold cyan]4. 상위 이미지 선별[/bold cyan]")
    ranker = ImageRanker()
    job = ranker.rank_job(job, top_n=top)
    console.print(f"  완료 {len(job.completed_tasks)}/{count}장 → 상위 {top}장 선별")

    # 5. 내보내기
    console.rule("[bold cyan]5. 결과 내보내기[/bold cyan]")
    exporter = Exporter()
    export_dir = exporter.export(job)
    console.print(f"  export 폴더: {export_dir}")

    # 결과 테이블 출력
    _print_results(job, top_n=top)

    console.rule()
    console.print(f"[bold green]✓ 완료! 결과 폴더: {job.output_dir}[/bold green]")
    console.print(f"  상위 이미지: {export_dir / 'top_results'}")
    console.print(f"  프롬프트 로그: {export_dir / 'prompt_log.json'}")
    console.print(f"  CSV 요약: {export_dir / 'results_summary.csv'}")


@cli.command()
@click.argument("job_id")
@click.option("--top", default=5, show_default=True, type=int, help="선별할 상위 이미지 수")
def rerank(job_id, top):
    """기존 Job의 결과를 재평가하여 상위 이미지 선별"""
    job = BatchRunner.load_job(job_id)
    if not job:
        console.print(f"[red]Job '{job_id}' 없음. outputs/ 폴더를 확인하세요.[/red]")
        raise SystemExit(1)

    ranker = ImageRanker()
    job = ranker.rank_job(job, top_n=top)

    exporter = Exporter()
    exporter.export(job)

    _print_results(job, top_n=top)
    console.print(f"\n[green]재선별 완료. 상위 {top}장 → {job.output_dir / 'export' / 'top_results'}[/green]")


@cli.command()
@click.argument("job_id")
@click.option("--top", default=5, show_default=True, type=int, help="포함할 상위 이미지 수")
@click.option("--zip", "create_zip", is_flag=True, default=False, help="ZIP으로 패키징")
def export(job_id, top, create_zip):
    """Job 결과를 export 폴더로 정리 (선택: ZIP 생성)"""
    job = BatchRunner.load_job(job_id)
    if not job:
        console.print(f"[red]Job '{job_id}' 없음.[/red]")
        raise SystemExit(1)

    exporter = Exporter()
    if create_zip:
        zip_path = exporter.create_zip(job)
        console.print(f"[green]ZIP 생성: {zip_path}[/green]")
    else:
        export_dir = exporter.export(job)
        console.print(f"[green]Export 완료: {export_dir}[/green]")


@cli.command("list-jobs")
@click.option("--limit", default=20, show_default=True, type=int, help="출력 최대 개수")
def list_jobs(limit):
    """완료된 Job 목록 출력"""
    output_dir = settings.output_dir
    if not output_dir.exists():
        console.print("[yellow]아직 생성된 Job 없음[/yellow]")
        return

    job_dirs = sorted(
        [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("job_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    if not job_dirs:
        console.print("[yellow]아직 생성된 Job 없음[/yellow]")
        return

    table = Table(title="Job 목록", show_lines=True)
    table.add_column("Job ID", style="cyan")
    table.add_column("상태", style="green")
    table.add_column("완료", justify="right")
    table.add_column("실패", justify="right", style="red")
    table.add_column("상위선별", justify="right", style="yellow")
    table.add_column("상품이미지")

    for job_dir in job_dirs[:limit]:
        meta_file = job_dir / "job_meta.json"
        if not meta_file.exists():
            continue
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        tasks = data.get("tasks", [])
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        failed = sum(1 for t in tasks if t.get("status") == "failed")
        top_count = len(data.get("top_results", []))
        product_path = Path(data.get("product_image_path", "")).name
        table.add_row(
            data.get("job_id", job_dir.name),
            data.get("status", "unknown"),
            str(completed),
            str(failed) if failed else "-",
            str(top_count) if top_count else "-",
            product_path,
        )

    console.print(table)


@cli.command("list-presets")
def list_presets():
    """사용 가능한 프리셋 목록 출력"""
    manager = PresetManager()
    collection_ids = manager.list_collections()

    if not collection_ids:
        console.print("[yellow]프리셋 없음. presets/ 폴더를 확인하세요.[/yellow]")
        return

    for cid in collection_ids:
        col = manager.get_collection(cid)
        console.print(f"\n[bold cyan]{col.name}[/bold cyan] (ID: [bold]{col.id}[/bold], category: {col.category})")
        table = Table(show_header=True, header_style="bold")
        table.add_column("ID")
        table.add_column("이름")
        table.add_column("설명")
        table.add_column("weight", justify="right")
        for p in col.presets:
            table.add_row(p.id, p.name, p.description[:50], str(p.weight))
        console.print(table)


# ── 내부 헬퍼 ─────────────────────────────────────────────────

def _print_results(job, top_n: int = 5):
    ranked = sorted(job.completed_tasks, key=lambda t: t.score or 0.0, reverse=True)
    top_ids = set(job.top_results)

    table = Table(title=f"결과 순위 (상위 {min(top_n, len(ranked))}장 ★)", show_lines=False)
    table.add_column("순위", width=4, justify="right")
    table.add_column("Task ID", style="dim", width=14)
    table.add_column("프리셋", width=26)
    table.add_column("점수", style="green", width=6, justify="right")
    table.add_column("배경")
    table.add_column("그림자")

    for rank, task in enumerate(ranked[:10], 1):
        marker = "★ " if task.task_id in top_ids else "  "
        table.add_row(
            f"{marker}{rank}",
            task.task_id[:12],
            task.preset_id,
            f"{task.score:.3f}" if task.score is not None else "-",
            task.variation.get("background", ""),
            task.variation.get("shadow", ""),
        )

    console.print(table)
