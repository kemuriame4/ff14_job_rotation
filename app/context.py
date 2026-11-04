from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .gamedata import merge_jobs
from .models import Job, Settings, load_jobs, load_settings, save_jobs, save_settings


class AppContext(QObject):
    job_changed = Signal()
    jobs_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[Job] = load_jobs()
        self.jobs, changed = merge_jobs(self.jobs)
        if changed:
            save_jobs(self.jobs)
        self.settings: Settings = load_settings()
        if not self.current_job_id() and self.jobs:
            self.settings.job_id = self.jobs[0].id

    def current_job_id(self) -> str:
        return self.settings.job_id

    def current_job(self) -> Job:
        job = self.job_by_id(self.settings.job_id)
        if job is None and self.jobs:
            job = self.jobs[0]
            self.settings.job_id = job.id
        return job

    def job_by_id(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def set_current_job(self, job_id: str) -> None:
        if self.job_by_id(job_id) is None or job_id == self.settings.job_id:
            return
        self.settings.job_id = job_id
        self.save_settings()
        self.job_changed.emit()

    def save_jobs(self) -> None:
        save_jobs(self.jobs)

    def save_settings(self) -> None:
        save_settings(self.settings)

    def notify_jobs_changed(self) -> None:
        self.save_jobs()
        self.jobs_changed.emit()
