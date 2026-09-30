# GrantRx scheduled automation

`scheduled_ingestion.yml` is the single authoritative scheduled scholarship catalog workflow.

- Runs daily at 03:00 UTC and partitions source categories across Monday-Saturday.
- Sunday is reserved for maintenance and the weekly student deadline digest.
- `scripts.repair_urls` runs exactly once per scheduled execution.
- Manual dispatch can run one category and optionally set a source limit.
- A concurrency group prevents overlapping catalog-maintenance runs.

Do not add a second scheduled scholarship scrape workflow. Extend the partition in
`scheduled_ingestion.yml` instead so categories, maintenance, and API usage remain predictable.
