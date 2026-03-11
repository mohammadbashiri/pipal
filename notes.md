### What an amazing agent should have

1. Stable identity + consistency (role, vibe, voice, boundaries).
2. User model (preferences, constraints, ongoing goals).
3. Context hygiene (what to remember vs ignore).
4. Reliable execution (tools, checklists, summaries).
5. Feedback loop (measure, adapt, persist changes).
6. Safety + trust (ask before risky actions, explain decisions).

### Make self-improvement real (a lightweight loop)

**Goal:** Improve collaboration quality over time.

**Signals (what to track):**
- User corrections ("No, I meant…")
- User preferences stated/changed
- Failed tasks or confusion
- Requests for more/less detail
- Repeated tasks (rituals)

**Process (monthly/weekly or after key events):**
1) Reflect: “What did I misunderstand or do well?”
2) Decide: “What one behavior change would help next time?”
3) Persist: Update POLICY/USER/MEMORY with a small rule or preference.
4) Verify: Ask the user to confirm if it’s okay.

### Make self-improvement operational (personal tasks)

**Approach:** Define self-improvement as an agent-specific routine and run it on a schedule.

**Mechanism:**
- Personal routines live in `~/.pal/agents/<name>/routines/`.
- Use the daemon/heartbeat to execute routines at regular intervals.
- Each run produces a one-line result (`ROUTINE_OK`/`ROUTINE_FAIL`) and is logged.

**Why this works:**
- Clear: the routine file defines explicit steps and output.
- Verifiable: daemon logs and run artifacts show it actually happened.
- Consistent: schedules enforce a cadence instead of relying on memory.
