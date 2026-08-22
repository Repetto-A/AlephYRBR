# Pears Track — research brief

## One-line thesis

Ship a standalone CLI that judges can install from a `pear://` link and update peer-to-peer over the air.

## Prize structure

- Total: up to **$1,500 USD₮**
- 1st: **$1,000 USD₮**
- 2nd: **$500 USD₮**
- Both prizes judge the same challenge.

## The actual challenge

Build a CLI on the Pear/Bare stack, deploy and seed it with the Pear CLI, and make this work:

```bash
pear install pear://<key>
```

Then demonstrate a real P2P OTA update reaching the installed copy. A repository that only builds locally does **not** qualify.

## Platform mental model

- **Bare** is the lightweight JavaScript runtime; do not assume Node.js APIs exist.
- **Pear CLI** handles build, deployment, seeding, and installation.
- **Pear OTA / `pear-runtime`** embeds P2P updates and app storage into the application.
- Distribution comes from the swarm, not a conventional app server, registry, or app store.
- A built app can become a standalone binary; users do not need Node or Pear development tooling.

## Choose the correct process shape

- Worker-thread updater: long-running TUI/REPL/service; isolates P2P work.
- Single-thread updater: simpler long-running processes.
- Detached daemon: short-lived one-shot commands that must exit while updates continue.

Matching process shape to product behavior is explicitly part of the judging signal.

## Strong project shapes

- A focused evergreen system utility.
- A terminal game that receives balance/content patches OTA.
- P2P chat, notes, presence, or file drop TUI.
- A developer tool that deserves to be a real cross-platform binary rather than a shell script.
- Experimental BLE discovery for offline room-scale apps.

## Hard requirements and gotchas

- Start from a `hello-pear-bare` variant.
- Deploy and seed a new `pear://` release during the event.
- Keep the link seeded through judging.
- Demonstrate working P2P OTA updates.
- Submit the `pear://` link and platforms built.
- Replace the template's placeholder `upgrade` URL with the real result of `pear touch`; otherwise `INVALID_URL` is expected.
- In the daemon variant, updater errors may go to `<storage>/updates.log` rather than the terminal.
- Pear/Bare is **not Node.js**. AI-generated Node imports, package assumptions, and imaginary CLI flags are a major failure mode.

## Submission evidence

- Public repo and README naming the starting variant.
- Installable, seeded `pear://` link.
- Demo showing both installation and an OTA update landing.
- List of platforms for which binaries were built.

## Feasibility profile

- **Fastest route:** tiny, useful one-shot CLI using the daemon updater shape.
- **Biggest hidden risk:** deployment/seeding/clean-machine installation, not business logic.
- **Best demo differentiator:** install on a second machine, ship an update live, and prove it arrives with no central server.

## Primary resources

- [Track brief](https://hacki.crecimiento.build/h/aleph-hackathon-2026/tracks/pears-track)
- [Pear CLI](https://docs.pears.com/reference/pear/cli/)
- [Pear OTA runtime](https://docs.pears.com/reference/pear/runtime/)
- [Storage and distribution](https://docs.pears.com/explanation/storage-and-distribution/)
- [`hello-pear-bare`](https://github.com/holepunchto/hello-pear-bare)
- [Pear documentation](https://docs.pears.com/)
