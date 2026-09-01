-- GrantRx: add calendar feed token and Stripe billing columns to profiles.

-- feed_token: opaque token used to authenticate the .ics calendar feed URL
--              without a JWT (so Apple/Google/Outlook can subscribe directly).
-- stripe_customer_id: Stripe customer object ID (cus_...).
-- stripe_subscription_id: Stripe subscription object ID (sub_...).
-- stripe_subscription_status: mirrors Stripe's subscription status string.

alter table profiles
    add column if not exists feed_token text unique,
    add column if not exists stripe_customer_id text,
    add column if not exists stripe_subscription_id text,
    add column if not exists stripe_subscription_status text;

-- Backfill feed tokens for existing profiles
update profiles
set feed_token = encode(gen_random_bytes(24), 'hex')
where feed_token is null;

-- Require a feed token going forward
alter table profiles
    alter column feed_token set not null;

-- RLS: the feed_token is used for the .ics endpoint, not direct table access.
-- Existing profile RLS policies still apply (users can only see their own row).
