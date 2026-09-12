-- MVP schema skeleton. Full migrations should be generated with Alembic.
create extension if not exists pgcrypto;

create table workspaces (id uuid primary key default gen_random_uuid(), name text not null, created_at timestamptz not null default now());
create table projects (id uuid primary key default gen_random_uuid(), workspace_id uuid not null references workspaces(id), name text not null, created_at timestamptz not null default now());
create table assets (id uuid primary key default gen_random_uuid(), workspace_id uuid not null references workspaces(id), sha256 text not null, storage_key text not null, format text, byte_size bigint not null, units text, created_at timestamptz not null default now(), unique(workspace_id, sha256, storage_key));
create table project_versions (id uuid primary key default gen_random_uuid(), project_id uuid not null references projects(id), parent_version_id uuid references project_versions(id), state text not null default 'finalized', created_at timestamptz not null default now());
create table version_assets (version_id uuid not null references project_versions(id), asset_id uuid not null references assets(id), role text not null, primary key(version_id, asset_id, role));
create table operations (id uuid primary key default gen_random_uuid(), project_version_id uuid not null references project_versions(id), sequence_no int not null, operation_type text not null, schema_version int not null, params jsonb not null, created_at timestamptz not null default now(), unique(project_version_id, sequence_no));
create table jobs (id uuid primary key default gen_random_uuid(), workspace_id uuid not null references workspaces(id), type text not null, status text not null, idempotency_key text, progress int not null default 0, input jsonb not null default '{}'::jsonb, result jsonb, error jsonb, created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create index jobs_active_idx on jobs(status, created_at) where status in ('queued','running','waiting_input');
