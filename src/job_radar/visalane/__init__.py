"""VisaLane backend services.

Bridges the mature Python scrape/classify pipeline to the VisaLane product
tables (jobs, companies, alerts, social_post_queue, job_people, analytics).

Submodules:
- db: service-role Supabase client (shared, lazy, fail-open)
- writer: canonical-URL-hash job upserts + company get_or_create
- alert_matching: alert filter matching over enriched job dicts
- social_queue: social_post_queue staging (LinkedIn/X -> manual_review)
- enrichment_stage: hiring-contact discovery via the 0-credit Apollo service
- stages: end-to-end post-scrape orchestration
- cli: cron entrypoint (`job-radar-visalane`)
"""
