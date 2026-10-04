# ADR-0001: Record decisions as ADRs and lessons in a learnings log

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user

## Context

This project will be worked on by many agents across many fresh conversations. Each conversation
starts without the reasoning behind earlier choices. Without a written record, decisions get
re-argued, lessons get re-learned, and a later agent can quietly undo something that was decided
for a good reason.

## Decision

- Every important decision gets an **ADR** in `docs/adr/`, numbered sequentially, using
  [template.md](template.md), and listed in [README.md](README.md).
- ADRs are **not rewritten** once accepted. To change a decision, write a new ADR that supersedes
  the old one and update the old one's status line only.
- Lessons (facts we discovered, surprises, gotchas) go in [docs/learnings.md](../learnings.md) as
  short dated entries with a link to the evidence. A lesson that changes a decision also gets an
  ADR.
- Experiments and measurements get a write-up in `docs/findings/`.
- `CLAUDE.md` tells every agent to read the ADR index and learnings before working, and to record
  new ones before finishing.

## Consequences

- Any agent can recover *why* things are the way they are by reading a handful of files.
- Small cost per decision. Decisions that are cheap to reverse and don't affect direction don't
  need an ADR.
- Decisions made before this ADR were backfilled as ADR-0002 to ADR-0008.

## Alternatives considered

- **Everything as ADRs, including lessons.** Rejected: many lessons are facts, not choices, and
  would bury the decisions.
- **One long notes file.** Rejected: hard to tell what's decided vs. observed, and no clean way to
  supersede.
- **Rely on git history and commit messages.** Rejected: agents rarely read history, and the
  reasoning usually happens before any code exists.
