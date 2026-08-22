# WDK Track — research brief

## One-line thesis

Build a real self-custodial wallet/payment product using Tether WDK as a core dependency, choosing either **WDK CLI/MCP** or **gasless payments**.

## Prize structure

- Total: up to **$1,500 USD₮**
- 1st: **$1,000 USD₮** — best project built with the WDK CLI and/or bundled MCP server.
- 2nd: **$500 USD₮** — best project using WDK gasless wallet modules.

The brief explicitly says to pick one prize direction and go deep.

## Direction A — WDK CLI / MCP

Core primitives:

- Create/unlock wallets, derive addresses, inspect balances/history, send native assets/tokens.
- Manage networks and custom tokens.
- Generate fiat on/off-ramp links.
- Use machine-readable `--json` output for scripts.
- Expose wallet operations to MCP-compatible agents.

Strong project shapes:

- Agent wallet with spending caps, allowlists, previews, and explicit confirmations.
- Treasury/payroll/bounty tool that previews batches and produces auditable receipts.
- Merchant terminal or invoice watcher that detects settlement and triggers a receipt/webhook.
- Testnet operations, faucet, portfolio TUI, or CI wallet backend.
- Agentic pay-per-call flows using x402.

What would make it competitive:

- The agent safety model is visible and testable.
- The project uses multiple meaningful wallet capabilities, not one wrapped command.
- Failures are safe: no silent broadcast, clear transaction preview, bounded authority.

## Direction B — gasless UX

Core thesis: users transact without holding a chain's native gas token; fees are sponsored or settled in USD₮/USD₮0.

Supported required module families include:

- Solana gasless (Kora-compatible paymaster)
- EVM EIP-7702 gasless
- EVM ERC-4337
- TON gasless
- TRON gas-free

Strong project shapes:

- Zero-to-first-payment onboarding.
- EIP-7702 batching or sponsored first transactions while keeping the user's existing EOA address.
- Gasless remittances/P2P transfers.
- Subscriptions, tipping, or micro-economies where native gas ruins UX.
- Cross-chain journeys combining gasless wallets with swaps or bridges.

## Hard requirements and gotchas

- Use `@tetherto/wdk` as a core dependency.
- CLI direction: use **`@tetherto/wdk-cli`**. The unscoped `wdk-cli` package is a different project.
- Gasless direction: use at least one named gasless WDK module and USD₮ as the fee token.
- Node.js **22.18.0+** is required by the track brief.
- WDK packages are beta; use a dedicated test wallet with limited funds.
- The hackathon does not provide paymaster endpoints. Obtain/configure your own.
- Testnet USD₮ support in the brief is limited to Sepolia via named providers. On other chains, use your own mock USD₮ or carefully budget small mainnet funds.
- The WDK integration must be new and central. A parallel or cosmetic integration is grounds for rejection.

## Submission evidence

- Public repo and clear README.
- Direct GitHub permalinks to WDK integration files/lines.
- Demo of the flow running end to end.
- Exact WDK packages and versions.
- Clean-clone setup and `.env.example`.
- Network/token details and mock-token address when applicable.

## Feasibility profile

- **Fastest route:** CLI/MCP developer tool with a constrained, auditable workflow.
- **Highest integration risk:** gasless cross-chain flow with external paymaster dependencies.
- **Best demo clarity:** show a user/agent completing a payment while enforcing a visible safety or gas abstraction guarantee.

## Primary resources

- [Track brief](https://hacki.crecimiento.build/h/aleph-hackathon-2026/tracks/wdk-track)
- [WDK documentation](https://docs.wdk.tether.io/)
- [WDK CLI reference](https://docs.wdk.tether.io/cli/api-reference/)
- [WDK MCP Toolkit](https://docs.wdk.tether.io/ai/mcp-toolkit/)
- [Wallet modules](https://docs.wdk.tether.io/sdk/wallet-modules/)
- [WDK GitHub](https://github.com/tetherto/wdk)
