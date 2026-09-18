# Observability (T-096, T-097)

## One id, end to end

Every request gets a trace id: taken from `X-Request-ID` if the client sent one, generated
otherwise, and always returned on the response. It appears in

- every log line the request writes (`trace_id`),
- the error envelope the client receives (`error.trace_id`),
- the `jobs.trace_id` column of any job the request queued,
- every log line the worker writes while running that job.

So a user who reports "it failed and said `9f2c…`" can be followed from the click to the
kernel run:

```bash
docker compose -f infra/docker-compose.yml logs api worker | grep 9f2c
```

Logs are one JSON object per line (`app/observability.py`). `APP_ENV=local` prints plain
text instead, because a human is reading it.

## Metrics

`GET /api/v1/metrics` returns Prometheus text. It is **disabled unless `METRICS_TOKEN` is
set**, and then requires `Authorization: Bearer $METRICS_TOKEN` — the numbers span every
workspace, so they are not public.

The values are computed from the same tables the product uses; there is no second counter
to drift.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `physicalai_jobs` | type, status | jobs created in the last 24 h |
| `physicalai_jobs_in_flight` | type | queued or running right now |
| `physicalai_job_duration_seconds_count/_sum` | type | finished job wall time, last 24 h |
| `physicalai_job_failures` | type, code | failures by error code, last 24 h |
| `physicalai_ai_cost_usd` | model | model spend, last 24 h |
| `physicalai_ai_tokens` | model | tokens billed, last 24 h |
| `physicalai_ai_calls` | model | provider calls, last 24 h |
| `physicalai_geometry_operations` | type | kernel operations ever executed |
| `physicalai_print_analyses` | status | printability analyses by verdict |
| `physicalai_scans` | status | scan sessions by state |

### Scrape config

```yaml
scrape_configs:
  - job_name: physical-ai-api
    scrape_interval: 60s
    metrics_path: /api/v1/metrics
    authorization:
      credentials: ${METRICS_TOKEN}
    static_configs:
      - targets: ["api:8000"]
```

A 60 s interval is deliberate: each scrape runs aggregate queries, and none of these
numbers move faster than that.

### Dashboard

`dashboard.json` imports into Grafana 11+ (Dashboards → New → Import). Three rows:

1. **Work** — jobs in flight, throughput by type, p-ish duration (sum/count), failures by code.
2. **AI** — spend and tokens per model, calls per hour.
3. **Geometry & scans** — operations by type, printability verdicts, scan funnel.

## Alerts worth having

| Condition | Why |
| --- | --- |
| `physicalai_jobs_in_flight` climbing for 15 min | the worker is down or wedged |
| `physicalai_job_failures{code="job_timeout"}` > 0 | work is being abandoned (T-095) |
| `physicalai_job_failures{code="kernel_unavailable"}` > 0 | the geometry binary is missing from the image |
| `physicalai_ai_cost_usd` above the daily budget | a runaway planner loop |
