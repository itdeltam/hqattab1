# config/

Non-secret, structured configuration lives here (e.g. strategy parameters,
risk-limit overrides by symbol/sector). Secrets (API keys, tokens) always
go in `.env`, never in this folder.

Nothing here yet — the risk engine (Stage 4) will add `risk_limits.yaml`,
and the strategy stage will add strategy parameter files.
