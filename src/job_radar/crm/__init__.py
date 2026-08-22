"""
src/job_radar/crm package
"""
from job_radar.crm.models import JobStatus, CRMJobRecord
from job_radar.crm.db import (
    init_crm_db,
    upsert_crm_job,
    update_job_status,
    list_crm_jobs,
    get_job_by_id,
    get_due_followups,
)

__all__ = [
    "JobStatus",
    "CRMJobRecord",
    "init_crm_db",
    "upsert_crm_job",
    "update_job_status",
    "list_crm_jobs",
    "get_job_by_id",
    "get_due_followups",
]
