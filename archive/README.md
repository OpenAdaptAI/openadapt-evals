# Archived Over-Designed Documentation

**Date Archived**: January 18, 2026
**Reason**: Complexity explosion - designs that were never implemented

## Files in This Directory

### WAA_RELIABILITY_PLAN.md (2,250 lines)
**What it describes**: Multi-layer health check system, circuit breakers, retry patterns
**What was implemented**: None of it
**Why archived**: The actual solution is simpler - a bash script executed via Azure CLI

### VM_SETUP_COMMAND.md (2,185 lines)
**What it describes**: VMSetupOrchestrator class with 9 phases, dataclasses, enums
**What was implemented**: None of it
**Why archived**: The actual vm-setup command is 305 lines of working bash, not a class hierarchy

### DOCKER_WAA_DESIGN_REVIEW.md (1,795 lines)
**What it describes**: Design review of WAA reliability issues, proposes Docker utilities module
**What was implemented**: None of it
**Why archived**: The problems are real, but the solution was over-engineered

## What Actually Works

See `SIMPLE_ARCHITECTURE.md` for what we actually have:
- vm-setup command: 305 lines of bash in cli.py
- Dashboard: Simple Flask server querying Azure CLI
- Container management: Direct `az vm run-command invoke` calls

## Lessons Learned

1. **Working code beats elegant design** - 295 lines of bash that works > 2,000 lines of classes that don't exist
2. **Design docs can be harmful** - They create the illusion of progress without delivering value
3. **YAGNI (You Aren't Gonna Need It)** - Don't build abstractions until you have 3+ duplicates
4. **Prefer bash over Python** - If it's a one-time VM operation, bash is probably simpler

## When to Resurrect These Docs

Only if:
1. We have 3+ duplicate implementations of the same pattern
2. The bash approach becomes unmaintainable (unlikely)
3. We need programmatic composition of health checks (not needed yet)

Until then, keep it simple.
