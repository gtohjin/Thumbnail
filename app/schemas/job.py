from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum
from pathlib import Path


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class GenerationTask(BaseModel):
    task_id: str
    job_id: str
    preset_id: str
    variation: Dict[str, str]
    prompt: str
    status: JobStatus = JobStatus.PENDING
    output_path: Optional[Path] = None
    score: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class Job(BaseModel):
    job_id: str
    product_image_id: str
    product_image_path: Path
    preset_collection_id: str
    total_count: int = 20
    tasks: List[GenerationTask] = []
    status: JobStatus = JobStatus.PENDING
    output_dir: Optional[Path] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    top_results: List[str] = []  # 상위 선별된 task_id 목록

    @property
    def completed_tasks(self) -> List[GenerationTask]:
        return [t for t in self.tasks if t.status == JobStatus.COMPLETED]

    @property
    def failed_tasks(self) -> List[GenerationTask]:
        return [t for t in self.tasks if t.status == JobStatus.FAILED]
