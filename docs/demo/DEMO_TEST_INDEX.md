# Demo Test Documentation Index

Quick navigation for all demo-conditioned prompting test materials.

---

## Start Here

**New to this?** → [`DEMO_TEST_SUMMARY.md`](./DEMO_TEST_SUMMARY.md)
1-page executive summary with key findings and recommendations.

**Ready to test?** → [`DEMO_TEST_QUICKSTART.md`](./DEMO_TEST_QUICKSTART.md)
Fast reference card with commands to run tests immediately.

**Want details?** → [`DEMO_TEST_PLAN.md`](./DEMO_TEST_PLAN.md)
10,000+ word comprehensive test plan with methodology and analysis.

**Need overview?** → [`DEMO_TEST_README.md`](./DEMO_TEST_README.md)
Complete guide to test suite, scenarios, and deliverables.

---

## By Use Case

### "I want to understand what this is about"
1. Read: [`DEMO_TEST_SUMMARY.md`](./DEMO_TEST_SUMMARY.md) (5 min)
2. Read: [`DEMO_TEST_README.md`](./DEMO_TEST_README.md) (10 min)
3. Optional: [`DEMO_TEST_PLAN.md`](./DEMO_TEST_PLAN.md) for deep dive

### "I want to run the tests now"
1. Check: [`DEMO_TEST_QUICKSTART.md`](./DEMO_TEST_QUICKSTART.md) - Prerequisites
2. Run: `./scripts/run_demo_test.sh --pilot`
3. Analyze: `python scripts/analyze_demo_results.py`
4. Review: Open `benchmark_results/*/viewer.html`

### "I want to understand the methodology"
1. Read: [`DEMO_TEST_PLAN.md`](./DEMO_TEST_PLAN.md) - Part 2 & 3 (Test Design & Scenarios)
2. Read: [`DEMO_TEST_PLAN.md`](./DEMO_TEST_PLAN.md) - Part 5 (Success Criteria)
3. Review: [`DEMO_VALIDATION_ANALYSIS_REPORT.md`](./DEMO_VALIDATION_ANALYSIS_REPORT.md) for research

### "I want to validate demo quality"
1. Read: [`DEMO_VALIDATION_ANALYSIS_REPORT.md`](./DEMO_VALIDATION_ANALYSIS_REPORT.md) (research-backed)
2. Read: [`DEMO_TEST_PLAN.md`](./DEMO_TEST_PLAN.md) - Part 6 (Synthetic Demo Validation)
3. Run: `uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos`

### "I want to troubleshoot issues"
1. Check: [`DEMO_TEST_QUICKSTART.md`](./DEMO_TEST_QUICKSTART.md) - Troubleshooting section
2. Check: [`DEMO_TEST_README.md`](./DEMO_TEST_README.md) - Troubleshooting section
3. Review: Execution logs in `benchmark_results/`

---

## Document Comparison

| Document | Length | Purpose | When to Use |
|----------|--------|---------|------------|
| **DEMO_TEST_SUMMARY.md** | 1 page | Executive summary | Quick overview, decisions |
| **DEMO_TEST_QUICKSTART.md** | 1 page | Command reference | Running tests quickly |
| **DEMO_TEST_README.md** | 3 pages | Test suite guide | Understanding deliverables |
| **DEMO_TEST_PLAN.md** | 50 pages | Comprehensive plan | Full methodology & analysis |
| **DEMO_TEST_INDEX.md** | 1 page | Navigation | Finding right document |

---

## Content Breakdown

### DEMO_TEST_SUMMARY.md
- What we're testing (hypothesis)
- The fix (code location)
- What we have ready (demos, infrastructure)
- Test design (3 scenarios)
- Execution plan (3 phases)
- Success criteria
- Cost estimates
- Critical dependencies

### DEMO_TEST_QUICKSTART.md
- TL;DR commands
- Prerequisites checklist
- Quick commands (pilot, full, custom)
- Manual execution (if scripts fail)
- View results
- Expected results table
- Troubleshooting
- Next steps

### DEMO_TEST_README.md
- What this is
- Quick start (4 steps)
- What's included (docs, scripts)
- Test scenarios (3)
- Success criteria
- Metrics tracked
- Execution phases
- Cost breakdown
- Results analysis
- Troubleshooting
- File organization

### DEMO_TEST_PLAN.md
**Part 1**: Baseline Establishment
**Part 2**: Demo Test Design
**Part 3**: Test Scenarios
**Part 4**: Test Execution Plan
**Part 5**: Success Criteria
**Part 6**: Synthetic Demo Validation
**Part 7**: Full Test Timeline
**Part 8**: Commands Reference
**Part 9**: Expected Results
**Part 10**: Final Recommendations

---

## Scripts & Tools

### `scripts/run_demo_test.sh`
Automated test runner.

**Usage**:
```bash
./scripts/run_demo_test.sh                    # Full test
./scripts/run_demo_test.sh --pilot            # Quick pilot
./scripts/run_demo_test.sh --task browser_5   # Custom task
./scripts/run_demo_test.sh --help             # Show options
```

**What it does**:
1. Checks prerequisites (VM, server, demos)
2. Runs baseline (no demo) 3 times
3. Runs treatment (with demo) 3 times
4. Runs negative control (wrong demo) 1 time
5. Analyzes results automatically

### `scripts/analyze_demo_results.py`
Results analysis script.

**Usage**:
```bash
python scripts/analyze_demo_results.py
python scripts/analyze_demo_results.py --results-dir custom_dir
python scripts/analyze_demo_results.py --export results.json
```

**What it does**:
1. Loads summary.json from all runs
2. Aggregates metrics (success rate, steps, time)
3. Compares scenarios (baseline vs treatment)
4. Calculates effect size
5. Evaluates success criteria
6. Exports to JSON (optional)

---

## Supporting Documentation

### DEMO_VALIDATION_ANALYSIS_REPORT.md
Research-backed analysis of demo validation approaches.

**Contents**:
- Literature review (agent evaluation methodologies)
- Cost data (human annotation, API, infrastructure)
- Time estimates (annotation, validation, execution)
- 5 validation approaches with cost/quality trade-offs
- Recommended hybrid approach ($33-86, 92-96% confidence)

**Use when**: Deciding how to validate synthetic demos

### REAL_EVALUATION_RESULTS.md
Guide to current WAA baseline results.

**Contents**:
- 7 real evaluations (Jan 16, 2026)
- Current state (0% success without demos)
- What's working (infrastructure)
- Next steps for improvement
- Running your own evaluation

**Use when**: Understanding current baseline performance

### SYNTHETIC_DEMOS_SUMMARY.md
Summary of synthetic demo generation project.

**Contents**:
- 154 demos generated (100% coverage)
- Generation approach (hybrid LLM + templates)
- Domain coverage (all 11 domains)
- Quality metrics (100% validated)
- Integration with ApiAgent

**Use when**: Understanding demo library

---

## File Locations

```
/Users/abrichr/oa/src/openadapt-evals/

Documentation (Start Here):
├── DEMO_TEST_INDEX.md                # This file - navigation
├── DEMO_TEST_SUMMARY.md              # 1-page executive summary
├── DEMO_TEST_QUICKSTART.md           # Fast command reference
├── DEMO_TEST_README.md               # Test suite guide
└── DEMO_TEST_PLAN.md                 # Comprehensive plan (10k+ words)

Supporting Docs:
├── DEMO_VALIDATION_ANALYSIS_REPORT.md  # Research & validation
├── REAL_EVALUATION_RESULTS.md          # Baseline results
└── SYNTHETIC_DEMOS_SUMMARY.md          # Demo generation

Scripts:
├── scripts/
│   ├── run_demo_test.sh              # Automated test runner
│   └── analyze_demo_results.py       # Results analysis

Demos:
└── demo_library/synthetic_demos/     # 154 synthetic demos
    ├── notepad_1.txt
    ├── browser_5.txt
    └── demos.json

Code:
└── openadapt_evals/agents/
    └── api_agent.py                  # Demo persistence fix (lines 371-379)

Results (Created During Tests):
└── benchmark_results/
    ├── baseline_run1/
    ├── treatment_run1/
    └── negative_control_run1/
```

---

## Common Workflows

### Workflow 1: Run Pilot Test
```bash
# 1. Start infrastructure
uv run python -m openadapt_evals.benchmarks.cli up

# 2. Run pilot
./scripts/run_demo_test.sh --pilot

# 3. Analyze
python scripts/analyze_demo_results.py

# 4. View
open benchmark_results/*/viewer.html
```

**Time**: 30 minutes
**Cost**: ~$2

### Workflow 2: Run Full Test
```bash
# 1. Start infrastructure
uv run python -m openadapt_evals.benchmarks.cli up

# 2. Run full test suite
./scripts/run_demo_test.sh

# 3. Analyze
python scripts/analyze_demo_results.py --export results.json

# 4. View & share
open benchmark_results/*/viewer.html
```

**Time**: 2 hours
**Cost**: ~$15

### Workflow 3: Validate Demo Quality
```bash
# 1. Format validation
uv run python -m openadapt_evals.benchmarks.validate_demos \
  --demo-dir demo_library/synthetic_demos

# 2. Execution test (1 demo)
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15

# 3. Review results
open benchmark_results/*/viewer.html
```

**Time**: 15 minutes
**Cost**: ~$1

---

## Decision Tree

```
START
│
├─ Need overview?
│  └─ Read: DEMO_TEST_SUMMARY.md
│
├─ Ready to test?
│  └─ Read: DEMO_TEST_QUICKSTART.md → Run: ./scripts/run_demo_test.sh --pilot
│
├─ Need methodology?
│  └─ Read: DEMO_TEST_PLAN.md (Parts 2, 3, 5)
│
├─ Validate demos?
│  └─ Read: DEMO_VALIDATION_ANALYSIS_REPORT.md → Run validation
│
├─ Understand baseline?
│  └─ Read: REAL_EVALUATION_RESULTS.md
│
└─ Lost?
   └─ You're here! (DEMO_TEST_INDEX.md)
```

---

## Quick Reference

| Task | Document | Section |
|------|----------|---------|
| Understand hypothesis | DEMO_TEST_SUMMARY.md | "What We're Testing" |
| See the fix | DEMO_TEST_SUMMARY.md | "The Fix" |
| Run pilot test | DEMO_TEST_QUICKSTART.md | "Pilot Test" |
| Run full test | DEMO_TEST_README.md | "Execution Phases" |
| Analyze results | DEMO_TEST_README.md | "Results Analysis" |
| Validate demos | DEMO_TEST_PLAN.md | Part 6 |
| Understand costs | DEMO_TEST_SUMMARY.md | "Cost Estimate" |
| Success criteria | DEMO_TEST_PLAN.md | Part 5 |
| Troubleshooting | DEMO_TEST_QUICKSTART.md | "Troubleshooting" |
| Next steps | DEMO_TEST_SUMMARY.md | "What Happens Next" |

---

## Status & Dependencies

**Current Status**: Ready to execute (waiting for WAA baseline)

**Blockers**:
- ⏳ WAA baseline validation (other agent's work)
- ⏳ Understanding of "good" performance metrics

**Ready**:
- ✅ Demo persistence fix implemented
- ✅ 154 synthetic demos validated
- ✅ Test infrastructure ready
- ✅ Comprehensive documentation

**Next Action**: Wait for baseline, then run pilot test

---

**Created**: January 18, 2026
**Version**: 1.0
**Maintained by**: OpenAdapt Team

---

**END OF INDEX**
