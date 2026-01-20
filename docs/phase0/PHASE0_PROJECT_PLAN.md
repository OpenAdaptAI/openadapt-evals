# Phase 0: Demo-Augmentation Prompting Baseline

**Status**: PLANNING
**Timeline**: 2 Weeks (Jan 20 - Feb 2, 2026)
**Budget**: $400
**Owner**: Research Team
**Decision Gate**: Feb 3, 2026

---

## Executive Summary

**Goal**: Systematically measure the impact of demo-conditioning on GUI agent performance using prompting BEFORE committing to expensive fine-tuning experiments.

**Hypothesis**: Demo-conditioned prompting will improve episode success rate by >20 percentage points compared to zero-shot baseline.

**Value**:
- LOW RISK validation ($400 vs $5k for fine-tuning)
- FAST turnaround (2 weeks vs 6 months)
- PUBLISHABLE results regardless of outcome
- DECISION DATA for fine-tuning investment

**Success Criteria**:
- All 240 runs complete (120 zero-shot + 120 demo-conditioned)
- Statistical significance achieved (p < 0.05)
- Clear decision at gate:
  - >20pp improvement = PROCEED to Phase 1 (training infrastructure)
  - 10-20pp improvement = ANALYZE cost-benefit of fine-tuning
  - <10pp improvement = PUBLISH prompting results, defer fine-tuning

---

## Timeline: 2 Weeks

### Week 1: Zero-Shot Baseline (Jan 20-26)

**Days 1-2 (Jan 20-21): Setup and Infrastructure Testing**
- [ ] Define 20-task evaluation set (diverse domains, first actions)
- [ ] Verify WAA server accessibility OR configure mock adapter fallback
- [ ] Test batch runner end-to-end (task load → API call → eval → metrics)
- [ ] Verify cost tracking integration (monitor API usage)
- [ ] Test statistical analysis pipeline (McNemar's test, bootstrap CI)

**Days 3-5 (Jan 22-24): Run 120 Zero-Shot Evaluations**
- [ ] Claude Sonnet 4.5: 20 tasks × 3 trials = 60 runs
- [ ] GPT-4V: 20 tasks × 3 trials = 60 runs
- [ ] Total: 120 runs (~$60-80 API cost)
- [ ] Monitor: Success rate, avg steps, common failure modes

**Days 6-7 (Jan 25-26): Initial Analysis**
- [ ] Compute zero-shot metrics (success rate, avg steps, time to complete)
- [ ] Categorize failure modes (coordinate errors, instruction misunderstanding, etc.)
- [ ] Generate preliminary viewer reports with screenshots
- [ ] Document issues and edge cases for demo-conditioned runs

### Week 2: Demo-Conditioned Baseline (Jan 27 - Feb 2)

**Days 8-10 (Jan 27-29): Run 120 Demo-Conditioned Evaluations**
- [ ] Claude Sonnet 4.5: 20 tasks × 3 trials = 60 runs (with retrieval demos)
- [ ] GPT-4V: 20 tasks × 3 trials = 60 runs (with retrieval demos)
- [ ] Total: 120 runs (~$60-80 API cost)
- [ ] Monitor: Demo retrieval quality, success rate, behavioral changes

**Days 11-12 (Jan 30-31): Statistical Analysis**
- [ ] Compute demo-conditioned metrics
- [ ] Statistical comparison: McNemar's test (paired trials)
- [ ] Bootstrap confidence intervals (95% CI on improvement)
- [ ] Effect size analysis (Cohen's d, odds ratio)
- [ ] Failure mode comparison (when demos help vs hurt)

**Days 13-14 (Feb 1-2): Decision Gate and Report**
- [ ] Generate final viewer reports (side-by-side comparison)
- [ ] Write Phase 0 final report (see PHASE0_FINAL_REPORT.md template)
- [ ] Present results to team
- [ ] DECISION: Proceed to Phase 1, publish prompting results, or pivot?

---

## Budget: $400

### Cost Breakdown

| Item | Quantity | Unit Cost | Subtotal |
|------|----------|-----------|----------|
| **API Calls** | | | |
| Claude Sonnet 4.5 (zero-shot) | 60 calls | $0.50 | $30 |
| Claude Sonnet 4.5 (demo) | 60 calls | $0.75 | $45 |
| GPT-4V (zero-shot) | 60 calls | $1.50 | $90 |
| GPT-4V (demo) | 60 calls | $2.00 | $120 |
| **Infrastructure** | | | |
| Azure VM (WAA server) | 100 hours | $0.20/hr | $20 |
| Storage (results) | 50 GB | $0.10/GB | $5 |
| **Contingency** | | | $90 |
| **TOTAL** | | | **$400** |

### Budget Alerts

- **50% threshold ($200)**: Review spending, ensure on track
- **75% threshold ($300)**: Reduce trials if needed (3 → 2 per task)
- **90% threshold ($360)**: STOP new runs, analyze existing data
- **100% threshold ($400)**: HARD STOP, no more API calls

### Cost Tracking

Budget tracking script: `scripts/phase0_budget.py`
- Real-time cost monitoring per run
- Automatic alerts when thresholds reached
- Breakdown by model, condition, task

---

## Success Criteria

### Primary Metrics

**Episode Success Rate**:
- Zero-shot baseline: X%
- Demo-conditioned: Y%
- Improvement: +Zpp (percentage points)
- Statistical significance: p < 0.05 (McNemar's test)

**Acceptance Thresholds**:
- **PROCEED (>20pp)**: Demo-augmentation clearly helps, invest in fine-tuning
- **ANALYZE (10-20pp)**: Marginal benefit, cost-benefit analysis needed
- **STOP (<10pp)**: Prompting insufficient, architectural changes needed

### Secondary Metrics

**Efficiency**:
- Average steps to completion (should decrease with demos)
- Time to task completion (should decrease with demos)
- First-action accuracy (expect high with demos, per P0 validation)

**Failure Modes**:
- Coordinate precision errors
- Instruction misunderstanding
- Timeout/max steps exceeded
- Application state errors

**Demo Quality**:
- Retrieval relevance (top-1 accuracy for demo selection)
- Demo format adherence (valid action syntax)

### Statistical Requirements

- **Sample size**: 20 tasks × 2 models × 2 conditions × 3 trials = 240 runs
- **Statistical tests**:
  - McNemar's test (paired trials, p < 0.05)
  - Bootstrap confidence intervals (95% CI, 10,000 resamples)
  - Effect size: Cohen's d, odds ratio
- **Multiple comparison correction**: Bonferroni correction if testing multiple hypotheses

### Deliverables

1. **Data**: 240 evaluation results (JSON + HTML viewer)
2. **Analysis**: Statistical report with p-values, confidence intervals, effect sizes
3. **Failure Modes**: Categorized analysis (when demos help vs hurt)
4. **Decision**: Clear recommendation for Phase 1 (go/no-go)

---

## Experimental Design

### Task Selection (20 tasks)

**Criteria**:
- Diverse domains: notepad (4), browser (4), office (4), system (4), coding (4)
- Diverse first actions: click (8), type (6), keyboard (3), wait (3)
- Difficulty range: simple (5), medium (10), hard (5)
- No outliers: exclude tasks with known bugs or environment issues

**Sampling Strategy**:
- Stratified random sampling from 154 WAA tasks
- Balanced across domains and difficulty levels
- Representative of full task distribution

### Experimental Conditions

**Condition 1: Zero-Shot Baseline**
- No demonstration provided
- System prompt only (task instruction + action syntax)
- Baseline for comparison

**Condition 2: Demo-Conditioned**
- Retrieve top-1 most relevant demo from library (154 synthetic demos)
- Demo prepended to EVERY step (P0 fix validated)
- Same system prompt as zero-shot

### Variables

**Independent Variables**:
- Condition: {zero-shot, demo-conditioned}
- Model: {Claude Sonnet 4.5, GPT-4V}
- Task: {20 selected tasks}

**Dependent Variables**:
- Episode success (binary: 0/1)
- Steps to completion (integer)
- Time to completion (seconds)
- First-action accuracy (binary: 0/1)

**Controlled Variables**:
- Max steps: 15
- Temperature: 0.0 (deterministic)
- System prompt template
- Action syntax

### Randomization

- Task order randomized per trial
- Model order randomized per task
- Condition order randomized per model-task pair
- Random seed fixed for reproducibility

---

## Infrastructure

### Required Components

**Existing (Ready)**:
- ✅ 154 synthetic demos (`demo_library/synthetic_demos/`)
- ✅ RetrievalAugmentedAgent (`openadapt_evals/agents/retrieval_agent.py`)
- ✅ WAALiveAdapter + WAAMockAdapter (`openadapt_evals/adapters/waa_live.py`)
- ✅ Evaluation harness (`openadapt_evals/benchmarks/runner.py`)
- ✅ Cost tracking (`openadapt_evals/benchmarks/monitoring.py`)
- ✅ Viewer + analysis (`openadapt_evals/benchmarks/viewer.py`)

**New (To Be Created)**:
- [ ] Batch runner for Phase 0 (`scripts/phase0_runner.py`)
- [ ] Budget tracker (`scripts/phase0_budget.py`)
- [ ] Results dashboard (`scripts/phase0_dashboard.py`)
- [ ] Statistical analysis script (`scripts/phase0_analysis.py`)

### Execution Environment

**Option A: Live WAA Server** (Preferred)
- Azure VM with WAA container (`waa-eval-vm`)
- Real Windows 11 environment
- Full task validation

**Option B: Mock Adapter** (Fallback)
- Local execution, no VM required
- Synthetic responses (coordinate validation only)
- Limited episode success measurement

**Decision**: Attempt Option A first, fall back to Option B if container issues persist.

---

## Risk Management

### High-Priority Risks

**Risk 1: Windows Container Blocks Evaluation**
- **Likelihood**: Medium (30%)
- **Impact**: High (cannot measure episode success)
- **Mitigation**: Use mock adapter for prompting baseline, fix container in parallel
- **Fallback**: Use behavioral metrics (avg steps, first-action accuracy) as proxy

**Risk 2: API Costs Exceed Budget**
- **Likelihood**: Low (10%)
- **Impact**: Medium (incomplete data)
- **Mitigation**: Real-time cost tracking, automatic budget alerts
- **Fallback**: Reduce trials (3 → 2 per task), analyze existing data

**Risk 3: Demo Retrieval Quality Issues**
- **Likelihood**: Low-Medium (20%)
- **Impact**: Medium (biased results)
- **Mitigation**: Validate retrieval relevance (top-1 accuracy), manual inspection
- **Fallback**: Use fixed demo assignment (best demo per domain)

**Risk 4: Statistical Power Insufficient**
- **Likelihood**: Low (10%)
- **Impact**: Medium (cannot reject null hypothesis)
- **Mitigation**: Power analysis (20 tasks × 3 trials = 90% power for 20pp effect)
- **Fallback**: Increase trials (3 → 5) within budget constraints

### Medium-Priority Risks

**Risk 5: Task Selection Bias**
- **Mitigation**: Stratified random sampling, document selection process
- **Fallback**: Sensitivity analysis (resample tasks, recompute metrics)

**Risk 6: Model API Downtime**
- **Mitigation**: Retry logic (3 attempts with exponential backoff)
- **Fallback**: Switch to backup model (GPT-4V ↔ Claude), continue runs

---

## Decision Gates

### Gate 1: Phase 0 Go/No-Go (Feb 3)

**Decision Criteria**:

| Improvement | Decision | Next Steps |
|-------------|----------|------------|
| **>20pp** | **PROCEED** to Phase 1 | Build training infrastructure, collect BC dataset |
| **10-20pp** | **ANALYZE** cost-benefit | Workshop paper + optional fine-tuning |
| **<10pp** | **STOP** fine-tuning | Publish prompting results, failure analysis |

**Required Data**:
- [ ] 240 runs complete (or >200 if budget constraints)
- [ ] Statistical significance achieved (p < 0.05)
- [ ] Failure modes categorized (at least 3 categories)
- [ ] Cost tracking complete (actual vs budget)

**Decision Makers**: Research team + advisor

**Output**: Written decision memo (see PHASE0_FINAL_REPORT.md)

---

## Deliverables

### Required Outputs

1. **Evaluation Results**
   - 240 JSON result files (per run)
   - Consolidated CSV (all runs, all metrics)
   - HTML viewer reports (screenshots + actions)

2. **Statistical Analysis Report**
   - Success rate comparison (zero-shot vs demo-conditioned)
   - Confidence intervals (95% bootstrap CI)
   - Statistical tests (McNemar's test, effect sizes)
   - Failure mode analysis (categorized by type)

3. **Failure Mode Categorization**
   - Taxonomy (coordinate, instruction, timeout, state)
   - Examples (annotated screenshots)
   - When demos help vs hurt

4. **Decision Gate Recommendation**
   - Go/no-go decision with justification
   - Cost-benefit analysis (prompting vs fine-tuning)
   - Next steps (Phase 1 plan or publication plan)

5. **Budget Report**
   - Actual vs estimated costs
   - Cost per run breakdown
   - Lessons learned for Phase 1

### Documentation

- [x] PHASE0_PROJECT_PLAN.md (this file)
- [ ] PHASE0_PROGRESS.md (daily updates)
- [ ] PHASE0_STANDUP.md (daily standup notes)
- [ ] PHASE0_WEEKLY_REVIEW.md (week-end review)
- [ ] PHASE0_FINAL_REPORT.md (decision gate report)

### Code

- [ ] `scripts/phase0_runner.py` (batch evaluation runner)
- [ ] `scripts/phase0_budget.py` (cost tracking)
- [ ] `scripts/phase0_dashboard.py` (progress dashboard)
- [ ] `scripts/phase0_analysis.py` (statistical analysis)

---

## Team & Resources

### Roles

- **Principal Investigator**: Research lead (strategy, decision gates)
- **Engineer**: Implementation, infrastructure, debugging
- **Analyst**: Statistical analysis, failure mode categorization

### Time Allocation

- **Week 1**: 40 hours (setup + zero-shot runs + initial analysis)
- **Week 2**: 40 hours (demo runs + statistical analysis + report)
- **Total**: 80 hours (1 FTE × 2 weeks = 0.5 person-months)

### External Dependencies

- **Azure VM**: WAA server access (or mock adapter fallback)
- **API Access**: Anthropic API (Claude), OpenAI API (GPT-4V)
- **Compute**: Local machine for analysis, Azure for evaluation

---

## Communication Plan

### Daily Standups

**Format**: See PHASE0_STANDUP.md template
**Frequency**: Every workday (5-10 min)
**Attendees**: Research team
**Topics**: Yesterday's progress, today's plan, blockers

### Weekly Reviews

**Format**: See PHASE0_WEEKLY_REVIEW.md template
**Frequency**: End of Week 1, End of Week 2
**Attendees**: Research team + advisor
**Topics**: Accomplishments, key findings, next week plan

### Decision Gate Meeting

**Date**: Feb 3, 2026
**Duration**: 60 min
**Attendees**: Research team + advisor
**Agenda**: Present results, discuss decision, align on next steps

---

## Appendix A: Related Work

**Demo-Conditioned Prompting**:
- Chain-of-Thought prompting (Wei et al., 2022)
- Few-shot learning (Brown et al., 2020)
- In-context learning (Dong et al., 2022)

**GUI Agents**:
- CogAgent (Hong et al., 2023)
- SeeClick (Cheng et al., 2024)
- Windows Agent Arena (Bonatti et al., 2024)

**Behavioral Cloning**:
- Imitation learning (Schaal, 1999)
- Learning from demonstrations (Argall et al., 2009)
- RT-2 robot learning (Brohan et al., 2023)

---

## Appendix B: Statistical Power Analysis

**Effect size**: 20pp improvement (0.3 → 0.5 success rate)
**Sample size**: 20 tasks × 3 trials = 60 paired samples
**Statistical test**: McNemar's test (paired proportions)
**Significance level**: α = 0.05
**Power**: 1 - β = 0.90

**Calculation**: Using G*Power 3.1
- Effect size w = 0.3 (medium-large effect)
- N = 60 pairs
- Power = 0.92 (sufficient for detecting 20pp effect)

**Conclusion**: 20 tasks × 3 trials provides sufficient statistical power to detect meaningful improvement.

---

**Document Version**: 1.0
**Last Updated**: 2026-01-18
**Status**: READY FOR REVIEW
