# Synthetic sprint history

Six fictional snapshots (26.16–26.21) are stored as `data/sprints/*.parquet`. The derived index is `data/history.parquet` and integrity metadata is `data/manifest.json`.

The records, Jira-like links, milestones, hours, team names, statuses and quality flags are invented for UI verification. No Amazon Quick, Jira, independent reviewer or sharpwriter execution has taken place. The `is_demo=true` flag must remain set; these files cannot be mixed with production snapshots.

Regenerate only in a clean checkout with no `data/` files:

```sh
uv run --with duckdb==1.5.6 python examples/generate_demo.py
```

This generator deliberately calls `publish_transaction` directly to bypass the *production-only* publication approval flow for **synthetic fixtures**. It must not be used for real Reporting data, and refuses to overwrite an existing release.

The dashboard's browser store uses Parquet, not this Markdown file or committed JSON.
