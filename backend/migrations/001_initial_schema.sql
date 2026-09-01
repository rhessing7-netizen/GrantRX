-- GrantRx Supabase initial schema
-- Run this in the Supabase SQL Editor (or psql) to create the database objects.

-- Enable pgcrypto for gen_random_uuid()
create extension if not exists "pgcrypto";

-- ENUMs

create type clinical_discipline as enum (
    'pharmacy',
    'medicine',
    'nursing',
    'therapeutics_rehab',
    'diagnostic_imaging',
    'public_health_emergency'
);

create type app_status as enum (
    'saved',
    'in_progress',
    'submitted',
    'awarded',
    'archived'
);

create type subscription_tier as enum (
    'free',
    'premium'
);

-- Profiles

create table if not exists profiles (
    id uuid primary key,
    primary_discipline clinical_discipline not null,
    target_credential varchar(64),
    clinical_phase varchar(64),
    gpa float not null,
    state_residence varchar(2) not null,
    sai_score integer,
    first_gen boolean default false,
    minority_flag boolean default false,
    professional_affiliations text[] default '{}',
    hobbies text[] default '{}',
    subscription_tier subscription_tier default 'free',
    searches_used_this_week integer default 0,
    search_cycle_reset_at timestamptz default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table profiles is 'Student profiles linked to Supabase Auth users.';

-- Scholarships

create table if not exists scholarships (
    id uuid primary key default gen_random_uuid(),
    title varchar(255) not null,
    provider varchar(255) not null,
    portal_url text not null,
    award_amount integer not null,
    deadline date not null,
    eligible_disciplines clinical_discipline[] not null,
    eligible_credentials text[] default '{}',
    min_gpa float default 0.0,
    max_sai integer,
    state_restrictions text[] default '{}',
    required_affiliations text[] default '{}',
    matching_tags text[] default '{}',
    is_archived boolean default false,
    estimated_next_cycle date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table scholarships is 'Scholarship opportunities ingested for matching.';

-- UserScholarships

create table if not exists user_scholarships (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    scholarship_id uuid not null references scholarships(id) on delete cascade,
    status app_status default 'saved',
    custom_deadline_reminder timestamptz,
    user_notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, scholarship_id)
);

comment on table user_scholarships is 'Kanban-style tracking of applications per user per scholarship.';

-- updated_at trigger helper

create or replace function update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger profiles_updated_at
    before update on profiles
    for each row
    execute function update_updated_at_column();

create trigger scholarships_updated_at
    before update on scholarships
    for each row
    execute function update_updated_at_column();

create trigger user_scholarships_updated_at
    before update on user_scholarships
    for each row
    execute function update_updated_at_column();

-- Row Level Security

alter table profiles enable row level security;
alter table scholarships enable row level security;
alter table user_scholarships enable row level security;

-- Profiles: users see and manage only their own profile

create policy "Users can insert their own profile"
    on profiles
    for insert
    to authenticated
    with check (auth.uid() = id);

create policy "Users can view own profile"
    on profiles
    for select
    to authenticated
    using (auth.uid() = id);

create policy "Users can update own profile"
    on profiles
    for update
    to authenticated
    using (auth.uid() = id)
    with check (auth.uid() = id);

create policy "Users can delete own profile"
    on profiles
    for delete
    to authenticated
    using (auth.uid() = id);

-- Scholarships: read-only for all authenticated users; full access for service role

create policy "Authenticated users can read scholarships"
    on scholarships
    for select
    to authenticated
    using (true);

create policy "Service role can manage scholarships"
    on scholarships
    for all
    to service_role
    using (true)
    with check (true);

-- UserScholarships: users manage only their own tracking rows

create policy "Users can insert own scholarship tracking"
    on user_scholarships
    for insert
    to authenticated
    with check (auth.uid() = user_id);

create policy "Users can view own scholarship tracking"
    on user_scholarships
    for select
    to authenticated
    using (auth.uid() = user_id);

create policy "Users can update own scholarship tracking"
    on user_scholarships
    for update
    to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can delete own scholarship tracking"
    on user_scholarships
    for delete
    to authenticated
    using (auth.uid() = user_id);
