# Roadmap

## Now

- Add deterministic unit tests for costs, matching, metrics, and strategy signals.
- Add small licensed fixtures so a smoke backtest runs without TuShare credentials.
- Version result metadata with config hash, data range, code revision, and fee model.

## Next

- Add walk-forward validation, benchmark comparison, and survivorship-bias checks.
- Expose read-only MCP tools for listing strategies and inspecting completed run results.
- Keep backtest execution as an explicit job with bounded inputs, timeouts, and audit metadata.

## Later

- Add experiment tracking and report comparison without committing generated runs to git.
- Integrate additional data providers behind the existing data interfaces.
