from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"


@dataclass
class Job:
    id: str
    state: str = STATE_RUNNING
    stage: str = "Empezando"
    progress: Optional[float] = None
    error: Optional[str] = None
    result: Any = None

    def report(self, stage: str, progress: Optional[float] = None) -> None:
        self.stage = stage
        self.progress = progress

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "stage": self.stage,
            "progress": self.progress,
            "error": self.error,
            "result": self.result,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    @staticmethod
    def _run(job: Job, work: Callable[[Job], Any]) -> None:
        try:
            job.result = work(job)
            job.state = STATE_DONE
            job.stage = "Terminado"
        except Exception as error:
            traceback.print_exc()
            job.error = str(error) or error.__class__.__name__
            job.state = STATE_FAILED
