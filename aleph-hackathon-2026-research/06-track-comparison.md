# Track comparison and decision matrix

## Fast comparison

| Track | Core proof | Prize pool | Best fit | Primary risk |
|---|---|---:|---|---|
| WDK CLI/MCP | Safe wallet/payment workflow using CLI or MCP | $1,000 first prize direction | Agentic payments, treasury, developer tooling | Security and cosmetic integration |
| WDK Gasless | User transacts without native gas | $500 second prize direction | Payments/remittances/onboarding | Paymaster and chain setup |
| Pears | `pear install` plus real P2P OTA update | $1,500 | CLI/TUI/P2P/offline tooling | Deployment, seeding, Bare compatibility |
| QVAC Ops | Useful private workflow runs locally | $1,000 first prize direction | Documents, finance ops, OCR | Model/hardware and messy-input quality |
| QVAC Reliability | Measured small-model tool reliability | $500 second prize direction | AI infra/evaluation/orchestration | Tool calling may exceed laptop model capability |
| General | Best execution and impact | $500 | Anything without a natural sponsor dependency | Broad field, weak differentiation |

## Decision questions

Choose **WDK** if:

- The product's core event is a payment, wallet operation, or financial transaction.
- You can make authorization, safety, or gas abstraction visible in the demo.
- You are comfortable managing test wallets and external chain infrastructure.

Choose **Pears** if:

- The product is naturally a CLI/TUI or local-first tool.
- P2P distribution or offline peer connectivity is itself part of the wow moment.
- You can test installation and updates on a clean second machine early.

Choose **QVAC** if:

- Privacy/offline local inference is essential rather than marketing.
- The workflow can be narrowly bounded and objectively evaluated.
- Your machine satisfies QVAC/model requirements.

Choose **General** if:

- No specialized technology is essential to the value proposition.
- Adding a sponsor SDK would be artificial.
- Execution quality and impact are stronger than sponsor alignment.

## Recommended risk-adjusted ranking

For a small team and a 24-hour build window:

1. **Pears, tightly scoped CLI** — crisp acceptance test and memorable deployment demo; validate tooling immediately.
2. **WDK CLI/MCP** — strong product surface and agent angle; security boundaries must be explicit.
3. **QVAC operations workflow** — compelling if hardware is ready and the task is narrow.
4. **WDK gasless** — strong UX but more third-party integration risk.
5. **QVAC general tool-use agent** — high upside, highest model reliability risk.
6. **General** — fallback when specialized integration would be forced.

This ranking is an inference from the published requirements, not an organizer recommendation.

## Go/no-go spike before committing

Spend the first 45–60 minutes proving the track's hardest dependency:

- WDK CLI/MCP: create a test wallet, read balance, execute a guarded dry-run or testnet transfer.
- WDK gasless: obtain paymaster configuration and complete one sponsored transfer.
- Pears: install a minimal seeded app from a second environment and push one OTA update.
- QVAC: run the target model locally and test the hardest input/tool sequence five times.

If the spike fails twice for environmental reasons, switch track early rather than building around an unproven dependency.
