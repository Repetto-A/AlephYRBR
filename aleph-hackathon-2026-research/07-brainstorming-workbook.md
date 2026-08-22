# Brainstorming workbook

Use this file directly in your IDE with an AI assistant. Do not start with features; start with the sponsor's required proof.

## 1. Constraints

- Team size:
- Available hardware/OS/RAM/GPU:
- Strongest languages/frameworks:
- Crypto experience:
- Local AI experience:
- Pear/Bare experience:
- External services we can configure quickly:
- Users or domain experts we can reach during the event:

## 2. Candidate problem

- Target user:
- Painful event that happens today:
- Current workaround:
- Why this matters now:
- Input available during a 3-minute demo:
- Observable successful output:
- Why the chosen track technology is indispensable:

## 3. Track-native proof

### WDK

- Which exact wallet/payment operation is core?
- What authority does the agent/user have?
- What guardrail prevents an unsafe transaction?
- How will the demo prove meaningful integration beyond one API call?

### Pears

- Why should this be a standalone CLI/TUI?
- Which process shape fits it?
- What changes in the live OTA update?
- How will judges install it on a clean machine?
- What user value comes from P2P distribution or connectivity?

### QVAC

- Why must data stay local?
- What narrow task can be measured repeatedly?
- What constitutes a hallucination or unsafe output?
- What deterministic validation surrounds the model?
- What model fits the available RAM and latency budget?

### General

- What is the technically difficult core?
- Why is the impact credible?
- What makes the solution different without sponsor-specific tooling?

## 4. One-sentence concepts

Use this format:

> For **[specific user]** who struggles with **[pain]**, **[project]** uses **[track-native capability]** to produce **[observable outcome]**, unlike **[current workaround]**.

Candidate A:

Candidate B:

Candidate C:

## 5. Score candidates

Score 1–5.

| Criterion | Weight | A | B | C |
|---|---:|---:|---:|---:|
| Sponsor alignment | 5 | | | |
| End-to-end feasibility in 24h | 5 | | | |
| 3-minute demo clarity | 5 | | | |
| Real user pain | 4 | | | |
| Technical depth | 4 | | | |
| Originality | 3 | | | |
| UI/UX/DX | 3 | | | |
| External dependency risk (reverse score) | 4 | | | |
| Evidence/testability | 4 | | | |

## 6. Vertical slice

- Demo start state:
- User action:
- Track technology invocation:
- Visible result:
- Failure case shown safely:
- Evidence captured for README/submission:

## 7. Kill list

Explicitly remove anything not needed for the judged proof:

- Authentication unless essential.
- Broad dashboards.
- Multiple chains/models/platforms before one works end to end.
- Generic chat UI without a differentiated workflow.
- Decorative sponsor integration.
- Features that cannot appear in the 3-minute demo.

## 8. Prompt for IDE brainstorming

```text
You are helping select an Aleph Hackathon 2026 project. Read the research files in this folder first. Generate 10 concepts for [TRACK], but reject any concept where the sponsor technology is cosmetic. For each concept provide: target user, painful job, track-native technical proof, 24-hour vertical slice, hardest dependency spike, demo moment, measurable success criterion, and main disqualification risk. Then rank the concepts using the matrix in 06-track-comparison.md. Do not propose implementation code yet.
```
