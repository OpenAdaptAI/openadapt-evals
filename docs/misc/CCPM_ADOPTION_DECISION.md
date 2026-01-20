# CCPM Adoption Decision: Personal Productivity Tool Evaluation

**Date**: 2026-01-18
**Question**: Should Richard use CCPM (Claude Code Project Manager) as a personal productivity tool to coordinate Claude Code sessions across OpenAdapt's repositories?

---

## CRITICAL CLARIFICATION

**This is NOT about**: Implementing CCPM features in OpenAdapt code
**This IS about**: Whether Richard should use CCPM as a tool to manage his own Claude Code workflow

CCPM is a standalone CLI tool (like git or tmux) that coordinates multiple Claude Code instances. The question is whether it would make Richard's daily work easier.

---

## Executive Summary

**Recommendation**: **DON'T ADOPT CCPM** - Stick with current approach and add lightweight coordination scripts

**Key Reasons**:
1. **Setup overhead outweighs benefits** - 2-4 hours setup for unclear time savings
2. **Workflow mismatch** - CCPM optimized for PRD→Epic→Task decomposition, Richard works more fluidly
3. **Single-repo limitation** - CCPM designed for monorepos, OpenAdapt has 6+ separate repos
4. **Simpler alternatives exist** - 30-line bash scripts can solve coordination pain points
5. **Conflicts with simplicity principles** - Current workflow already works, CCPM adds complexity

**Alternative**: Build 4 lightweight scripts (total: 2 hours) to solve actual pain points

---

## Current Workflow Analysis

### What Richard Actually Does (Based on Today's Session)

**Session Stats** (2026-01-18):
- 10 parallel Claude Code agents launched manually
- Modified files across 6 repositories
- 3 PRs merged, 2 PRs closed, 1 PR created
- Updated `/Users/abrichr/oa/src/STATUS.md` manually
- Used `gh pr` commands for GitHub coordination
- Switched between repos manually

**Pain Points**:
1. ✅ **Managing work across 6 repos** (evals, ml, viewer, capture, web, tray)
2. ✅ **Keeping STATUS.md updated** - Manual editing after each session
3. ✅ **Tracking uncommitted changes** - Need to check git status in all repos
4. ✅ **Coordinating PRs** - Merging PRs across repos manually
5. ✅ **Context switching** - Opening Claude Code in different repos
6. ❌ **Task decomposition** - NOT a pain point (Richard works fluidly, not rigidly)

**Current Tools**:
- STATUS.md (single source of truth)
- GitHub CLI (`gh pr list`, `gh pr merge`)
- Background agents (`claude-code --background`)
- Manual coordination via file system

**What Works Well**:
- ✅ STATUS.md provides clear priorities
- ✅ Background agents enable parallelism
- ✅ GitHub CLI handles PR operations
- ✅ Simple, predictable, no hidden magic
- ✅ Already validated through heavy use

---

## CCPM Workflow Analysis

### What CCPM Offers

**Installation**:
- Time: 2-5 minutes (basic install)
- Setup: 15-30 minutes (per repository configuration)
- Learning curve: 2-3 sessions to proficiency

**Core Workflow**:
```bash
# 1. Create PRD (Product Requirements Document)
/pm:prd-new feature-name

# 2. Parse PRD into Epic with tasks
/pm:prd-parse feature-name

# 3. Decompose epic into tasks
/pm:epic-decompose feature-name

# 4. Push to GitHub Issues
/pm:epic-oneshot feature-name

# 5. Start tasks
/pm:issue-start 1234

# 6. Sync progress
/pm:issue-sync 1234

# 7. Check status
/pm:status
```

**Daily Commands**:
- `/pm:next` - Get next task
- `/pm:issue-sync` - Update progress
- `/pm:status` - Check dashboard
- `/pm:standup` - Session summary

**Technology**:
- Uses GitHub Issues as database
- Git worktrees for parallel work
- `.claude/` directories per repo
- Issue comments for progress tracking

### Concrete Example: Today's Work With CCPM

**Today's actual work**:
1. 10 parallel agents (WAA fix, PR merges, cleanup, demo strategy)
2. Modified 3+ repos simultaneously
3. Manual STATUS.md updates
4. GitHub CLI for PR operations

**How CCPM would handle this**:

**Setup phase (30-60 minutes ONE-TIME)**:
```bash
# Initialize each repo
cd /Users/abrichr/oa/src/openadapt-evals
/pm:init

cd /Users/abrichr/oa/src/openadapt-ml
/pm:init

cd /Users/abrichr/oa/src/openadapt-viewer
/pm:init

# ... repeat for 6 repos
```

**Daily workflow (SLOWER than current)**:

Instead of:
```bash
# Current (30 seconds)
cat STATUS.md  # Read P0 priorities
claude-code --background "Fix WAA integration"
```

CCPM requires:
```bash
# CCPM (3-5 minutes)
/pm:prd-new waa-integration-fix
# Answer guided prompts about requirements
/pm:prd-parse waa-integration-fix
# Wait for LLM to analyze and create epic
/pm:epic-decompose waa-integration-fix
# Wait for task breakdown
/pm:epic-oneshot waa-integration-fix
# Push to GitHub Issues
/pm:issue-start 1234
# Finally start work
```

**For 10 parallel tasks**: 30-50 minutes of CCPM ceremony vs. 5 minutes current approach

---

## Multi-Repository Challenge

### CCPM's Architecture

**Designed for**: Single repository (monorepo)
- `.claude/` directory in repo root
- PRDs, epics, tasks all in one place
- Git worktrees for parallel branches

**OpenAdapt's Reality**: 6+ separate repositories
- openadapt-evals (benchmarks)
- openadapt-ml (training)
- openadapt-viewer (UI)
- openadapt-capture (recording)
- openadapt-web (landing page)
- openadapt-tray (system tray app)

**Problem**: CCPM has no cross-repo coordination
- Each repo needs separate initialization
- No unified task view across repos
- Issues scattered across 6 GitHub repos
- No way to track "change viewer + web + evals together"

**Example from today**:
- Agent 1: Fix WAA integration (openadapt-evals)
- Agent 2: Merge PR #14 (openadapt-evals)
- Agent 3: Merge PR #4 (openadapt-capture)
- Agent 4: Merge PR #4 (openadapt-viewer)

With CCPM: Need 3 separate epics in 3 repos, manual coordination

With STATUS.md: All tracked in one file, simple

---

## Time Investment Analysis

### Setup Cost

**Initial setup** (per repository):
- Install CCPM: 2-5 minutes
- Initialize repo: 5-10 minutes (run `/pm:init`, configure)
- Learn workflow: 30-60 minutes (first time)
- Configure GitHub integration: 10-20 minutes

**Total for 6 repos**: 3-4 hours

**Ongoing overhead** (per task):
- Create PRD: 2-5 minutes
- Parse/decompose: 3-5 minutes (LLM processing)
- Issue sync: 1-2 minutes per update
- Status checks: 30-60 seconds

**Daily overhead**: +15-30 minutes vs. current workflow

### Expected Time Savings

**What CCPM could save**:
- ❓ GitHub Issues tracking (but Richard uses STATUS.md, not Issues)
- ❓ Context preservation (but STATUS.md already does this)
- ❓ Parallel task coordination (but background agents already work)

**Realistic savings**: 0-5 minutes per day
- GitHub Issues already accessible via `gh issue`
- STATUS.md is simpler than navigating Issues
- Context switching is fast (just open different directory)

**Break-even analysis**:
- Setup cost: 3-4 hours (240 minutes)
- Daily savings: 0-5 minutes
- Break-even: 48-240 days (1.5-8 months)

**Verdict**: NOT worth it for marginal savings

---

## Workflow Compatibility Analysis

### Richard's Actual Work Style

**Observed patterns** (from STATUS.md and session history):
1. **Fluid prioritization** - Shifts between P0/P1/P2 as needed
2. **Opportunistic parallelism** - Launches agents when work is parallelizable
3. **Simple tracking** - STATUS.md, not formal task management
4. **Direct action** - Sees problem, fixes it, commits, moves on
5. **Lightweight documentation** - CLAUDE.md, STATUS.md, design docs as needed

**Example**: Today's WAA integration fix
- Saw problem (task loading broken)
- Analyzed root cause
- Fixed 3 files
- Validated fix
- Moved to next priority

**Total time**: ~2 hours, pure execution

### CCPM's Workflow Philosophy

**CCPM requires**:
1. **Rigid structure** - PRD → Epic → Task → Issue → Code
2. **Upfront planning** - Write PRD before coding
3. **Spec-driven development** - "Every line traces to spec"
4. **Formal decomposition** - Break work into GitHub Issues
5. **Progress tracking** - Sync after every change

**Example**: Same WAA fix with CCPM
1. `/pm:prd-new waa-integration-fix` (5 min)
2. Answer guided prompts about requirements
3. `/pm:prd-parse waa-integration-fix` (3 min)
4. `/pm:epic-decompose waa-integration-fix` (3 min)
5. `/pm:epic-oneshot waa-integration-fix` (2 min)
6. `/pm:issue-start 1234` (start work)
7. Code changes (2 hours)
8. `/pm:issue-sync 1234` (1 min)
9. `/pm:issue-close 1234` (1 min)

**Total time**: ~2 hours 15 minutes (15 minutes overhead)

**Verdict**: CCPM's structure conflicts with fluid work style

---

## Simplicity Principles Evaluation

### From SIMPLICITY_PRINCIPLES.md

**Key questions**:
1. ✅ **Does CCPM solve a real, immediate problem?** → NO
   - Current workflow works
   - Pain points are minor (repo coordination)
   - STATUS.md already provides centralized tracking

2. ❌ **Can this be solved in <100 lines?** → NO
   - CCPM is a complex system (GitHub Issues, worktrees, LLM integration)
   - Lightweight scripts could solve actual pain points in 30 lines each

3. ❌ **Is this the simplest approach?** → NO
   - Current workflow: Read STATUS.md, launch Claude Code
   - CCPM workflow: /pm:prd-new → /pm:prd-parse → /pm:epic-decompose → ...
   - Bash scripts for repo coordination: Simpler

4. ❌ **Does this provide 80% of value with 20% of complexity?** → NO
   - 3-4 hours setup + 15-30 min daily overhead
   - Saves 0-5 minutes per day
   - Ratio: 20% value, 80% complexity

**Philosophy conflict**:
- "Working code beats elegant design" - Current workflow works
- "If it works, ship it" - STATUS.md works, don't replace it
- "The best code is the code you didn't write" - Don't add CCPM

**Verdict**: CCPM violates simplicity principles

---

## Alternative: Lightweight Coordination Scripts

### Actual Pain Points (Prioritized)

1. ✅ **Tracking uncommitted changes** (High pain)
   - Manual `git status` in 6 repos
   - Easy to forget where work is

2. ✅ **Multi-repo status** (Medium pain)
   - Want to see all repos at once
   - Current: Manual `gh pr list` per repo

3. ✅ **PR coordination** (Low pain)
   - GitHub CLI mostly handles this
   - Just need batch operations

### Proposed Scripts (Total: 90 lines)

**1. repos-dirty.sh** (20 lines)
```bash
#!/bin/bash
# Show uncommitted changes across all OpenAdapt repos

REPOS=(
  /Users/abrichr/oa/src/openadapt-evals
  /Users/abrichr/oa/src/openadapt-ml
  /Users/abrichr/oa/src/openadapt-viewer
  /Users/abrichr/oa/src/openadapt-capture
  /Users/abrichr/oa/src/openadapt-web
  /Users/abrichr/oa/src/openadapt-tray
)

echo "=== Uncommitted Changes ==="
for repo in "${REPOS[@]}"; do
  cd "$repo" || continue
  if ! git diff-index --quiet HEAD --; then
    echo "📝 $(basename "$repo"):"
    git status --short
  fi
done
```

**2. repos-prs.sh** (15 lines)
```bash
#!/bin/bash
# List all open PRs across OpenAdapt repos

echo "=== Open Pull Requests ==="
gh pr list --repo OpenAdaptAI/openadapt-evals --state open
gh pr list --repo OpenAdaptAI/openadapt-ml --state open
gh pr list --repo OpenAdaptAI/openadapt-viewer --state open
gh pr list --repo OpenAdaptAI/openadapt-capture --state open
gh pr list --repo OpenAdaptAI/openadapt-web --state open
gh pr list --repo OpenAdaptAI/openadapt-tray --state open
```

**3. repos-status.sh** (30 lines)
```bash
#!/bin/bash
# Unified status across all repos

echo "=== OpenAdapt Repository Status ==="
echo ""

REPOS=(openadapt-evals openadapt-ml openadapt-viewer openadapt-capture openadapt-web openadapt-tray)

for repo in "${REPOS[@]}"; do
  cd "/Users/abrichr/oa/src/$repo" || continue

  echo "📁 $repo:"

  # Uncommitted changes
  if ! git diff-index --quiet HEAD --; then
    echo "  ⚠️  Uncommitted changes"
  fi

  # Open PRs
  pr_count=$(gh pr list --repo "OpenAdaptAI/$repo" --state open --limit 100 --json number | jq '. | length')
  if [ "$pr_count" -gt 0 ]; then
    echo "  🔀 $pr_count open PRs"
  fi

  # Recent commits
  last_commit=$(git log -1 --format="%cr")
  echo "  📅 Last commit: $last_commit"

  echo ""
done
```

**4. repos-sync.sh** (25 lines)
```bash
#!/bin/bash
# Pull latest changes from all repos

REPOS=(
  /Users/abrichr/oa/src/openadapt-evals
  /Users/abrichr/oa/src/openadapt-ml
  /Users/abrichr/oa/src/openadapt-viewer
  /Users/abrichr/oa/src/openadapt-capture
  /Users/abrichr/oa/src/openadapt-web
  /Users/abrichr/oa/src/openadapt-tray
)

echo "=== Syncing All Repos ==="
for repo in "${REPOS[@]}"; do
  echo ""
  echo "📦 Syncing $(basename "$repo")..."
  cd "$repo" || continue

  # Check if repo is dirty
  if ! git diff-index --quiet HEAD --; then
    echo "⚠️  Skipping (uncommitted changes)"
    continue
  fi

  git pull
done
```

### Time Investment Comparison

| Approach | Setup | Daily Overhead | Solves Pain Points |
|----------|-------|----------------|-------------------|
| CCPM | 3-4 hours | +15-30 min | No (different workflow) |
| Bash scripts | 2 hours | -5 min | Yes (exact pain points) |
| Current | 0 hours | 0 min | Partially |

**Scripts advantages**:
- Solve actual pain points (repo coordination)
- Faster than current workflow
- Simple (90 lines total)
- No learning curve
- No ongoing overhead
- Composable with existing tools

**Scripts ROI**:
- Setup: 2 hours
- Daily savings: 5 minutes (checking repos)
- Break-even: 24 days (3.5 weeks)

---

## Decision Matrix

### Adopt CCPM if...
- ❌ Reduces manual coordination time (saves >1 hour/week)
  - **Reality**: Adds 15-30 min/day overhead
- ❌ Setup cost < 4 hours
  - **Reality**: 3-4 hours (borderline)
- ❌ Easier than current workflow after learning curve
  - **Reality**: More ceremony, slower
- ❌ Works well with existing repos/setup
  - **Reality**: Designed for monorepos, not multi-repo
- ❌ Doesn't conflict with simplicity principles
  - **Reality**: Violates "working code beats design" principle

**Score**: 0/5 criteria met

### Don't Adopt if...
- ✅ Adds complexity without clear time savings
  - **Confirmed**: +15-30 min overhead for unclear benefits
- ✅ Setup cost > 8 hours (or borderline with unclear ROI)
  - **Confirmed**: 3-4 hours setup, 1.5-8 months break-even
- ✅ Harder than current workflow
  - **Confirmed**: More steps, more ceremony
- ✅ Requires major repo restructuring
  - **Confirmed**: Each repo needs `/pm:init`, Issues migration
- ✅ Steep learning curve (>2 weeks to proficiency)
  - **Borderline**: 2-3 sessions, but workflow mismatch persists

**Score**: 4.5/5 criteria met (clear DON'T ADOPT)

---

## Recommendation

### PRIMARY RECOMMENDATION: Don't Adopt CCPM

**Instead**: Build 4 lightweight bash scripts (2 hours total)

**Scripts to create**:
1. `repos-dirty.sh` - Find uncommitted changes (20 lines)
2. `repos-prs.sh` - List all open PRs (15 lines)
3. `repos-status.sh` - Unified status dashboard (30 lines)
4. `repos-sync.sh` - Pull all repos at once (25 lines)

**Expected productivity gain**:
- Save 5 minutes per day checking repos
- Break-even in 3.5 weeks
- No learning curve
- No ongoing overhead
- Works with existing workflow

**Where to put them**: `/Users/abrichr/oa/src/scripts/`

### If Scripts Aren't Enough

**Re-evaluate CCPM if**:
1. Multi-repo coordination becomes critical blocker (>1 hour/day wasted)
2. GitHub Issues become primary tracking method (replacing STATUS.md)
3. Team grows beyond 1 person (CCPM excels at team coordination)
4. Work style shifts to PRD-driven (spec-first development)

**Current verdict**: None of these apply

---

## Next Steps

### Immediate Actions (2 hours)

**1. Create scripts directory** (5 minutes)
```bash
mkdir -p /Users/abrichr/oa/src/scripts
cd /Users/abrichr/oa/src/scripts
```

**2. Write repos-dirty.sh** (30 minutes)
- Test with all 6 repos
- Add color output
- Handle edge cases (repo not found, etc.)

**3. Write repos-prs.sh** (20 minutes)
- Test with GitHub CLI
- Format output nicely
- Show PR titles and numbers

**4. Write repos-status.sh** (40 minutes)
- Combine dirty check + PR check
- Add branch info
- Show last commit date

**5. Write repos-sync.sh** (20 minutes)
- Test pull on all repos
- Handle merge conflicts gracefully
- Show summary at end

**6. Add to PATH and test** (10 minutes)
```bash
# Add to ~/.zshrc or ~/.bashrc
export PATH="$PATH:/Users/abrichr/oa/src/scripts"

# Make executable
chmod +x /Users/abrichr/oa/src/scripts/*.sh

# Test
repos-status.sh
```

### Trial Period (1 week)

**Use scripts daily**:
- Morning: `repos-status.sh` (check overnight changes)
- Before session: `repos-dirty.sh` (find uncommitted work)
- After session: Update STATUS.md as usual

**Measure**:
- Time saved per day
- Friction points (what's still annoying?)
- Additional features needed

**Decision point** (after 1 week):
- Scripts working well? → Keep using, iterate
- Still painful? → Consider other solutions
- CCPM still appealing? → Re-evaluate with fresh data

### Long-term Strategy

**Keep current workflow** (STATUS.md + scripts):
- STATUS.md: Strategic priorities (P0/P1/P2)
- Scripts: Tactical coordination (repos, PRs)
- GitHub CLI: PR operations
- Background agents: Parallelism

**When to revisit CCPM**:
- Team size > 2 people
- GitHub Issues become primary workflow
- Multi-repo coordination dominates daily work (>1 hour/day)
- Need formal spec-driven development

**Current estimate**: Re-evaluate in 6-12 months

---

## Appendix: CCPM Research Summary

### Sources

Based on research from:
- [GitHub - automazeio/ccpm](https://github.com/automazeio/ccpm)
- [CCPM Commands Documentation](https://github.com/automazeio/ccpm/blob/main/COMMANDS.md)
- [CCPM Installation Guide](https://github.com/automazeio/ccpm/blob/main/install/README.md)
- [Claude Code PM for Beginners](https://ossels.ai/claude-code-pm-beginners-ai-project-management/)
- [CCPM: Claude Code Project Manager | Killer Code](https://cc.deeptoai.com/docs/en/tools/ccpm-claude-code-project-manager)

### Key Findings

**What CCPM does well**:
- ✅ Parallel agent coordination (multiple Claude instances)
- ✅ Persistent context across sessions (`.claude/context/`)
- ✅ Audit trail in GitHub Issues
- ✅ Team collaboration (visible progress)
- ✅ Structured workflow (PRD → Epic → Task)

**What CCPM doesn't do**:
- ❌ Cross-repository coordination (monorepo only)
- ❌ Lightweight ad-hoc tasks (requires PRD overhead)
- ❌ Fluid priority shifts (spec-driven rigidity)
- ❌ Simple status tracking (GitHub Issues vs. STATUS.md)

**Best use cases for CCPM**:
1. Large monorepo projects
2. Team of 2+ developers
3. Compliance/audit requirements
4. Spec-driven development culture
5. Complex features (4+ parallel workstreams)

**Not recommended for**:
1. Multi-repo projects (like OpenAdapt)
2. Solo developers (Richard's case)
3. Fluid, opportunistic workflows
4. Simple coordination needs

### Installation Notes

**Quick install**:
```bash
# macOS/Linux
curl -sSL https://automaze.io/ccpm/install | bash

# Windows
iwr -useb https://automaze.io/ccpm/install | iex
```

**Per-repo setup**:
```bash
cd /your/repo
/pm:init  # Creates .claude/ directory, configures GitHub
```

**Time estimate**: 2-5 minutes install, 15-30 minutes per repo setup

### Workflow Commands

**Daily use**:
- `/pm:next` - Get next prioritized task
- `/pm:issue-sync 1234` - Update progress
- `/pm:status` - View dashboard
- `/pm:standup` - Generate session summary

**Epic management**:
- `/pm:prd-new feature` - Create PRD
- `/pm:prd-parse feature` - Parse into epic
- `/pm:epic-decompose feature` - Break into tasks
- `/pm:epic-oneshot feature` - Push to GitHub

**Monitoring**:
- `/pm:blocked` - Show blocked tasks
- `/pm:in-progress` - Show active work
- `/pm:validate` - Check consistency

---

## Conclusion

**CCPM is a well-designed tool** for spec-driven development in monorepos with team collaboration needs.

**For Richard's use case**: Wrong tool for the job.

**Better solution**: 4 lightweight bash scripts (2 hours) that solve actual pain points without workflow overhead.

**Re-evaluate when**: Team grows, workflow changes, or multi-repo coordination becomes critical blocker (>1 hour/day).

**Next action**: Build `repos-dirty.sh`, `repos-prs.sh`, `repos-status.sh`, `repos-sync.sh` and trial for 1 week.

---

**Decision**: ❌ DON'T ADOPT CCPM
**Alternative**: ✅ BUILD LIGHTWEIGHT SCRIPTS
**Timeline**: 2 hours setup, 1 week trial, re-evaluate in 6-12 months
