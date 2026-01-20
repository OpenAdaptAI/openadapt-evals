# Phase 0 Final Report: Demo-Augmentation Prompting Baseline

**Date**: [To be completed]
**Status**: TEMPLATE
**Decision Gate**: Feb 3, 2026
**Authors**: Research Team

---

## Executive Summary

**Objective**: Measure the impact of demo-conditioning on GUI agent performance using prompting to inform decision on fine-tuning investment.

**Methodology**: 240 evaluations (20 tasks × 2 models × 2 conditions × 3 trials) comparing zero-shot vs demo-conditioned prompting.

**Results Summary**:
- Zero-shot success rate: X% (Claude), Y% (GPT-4V)
- Demo-conditioned success rate: X% (Claude), Y% (GPT-4V)
- Improvement: +Xpp (95% CI: [Y, Z])
- Statistical significance: p = X (McNemar's test)
- Effect size: Cohen's d = X (small/medium/large)

**Decision**: [PROCEED / ANALYZE / STOP]

**Recommendation**: [Brief 1-2 sentence recommendation]

---

## 1. Background

### 1.1 Motivation

Demo-augmented prompting has shown promise in preliminary testing:
- P0 fix validation: 3.0 vs 6.8 avg steps (mock test)
- 100% first-action accuracy in manual demos
- Behavioral change confirmed

**Research Question**: Does demo-conditioning in prompts improve episode success rate enough to warrant expensive fine-tuning experiments?

### 1.2 Objectives

**Primary Objective**: Quantify demo-conditioning impact on episode success rate

**Secondary Objectives**:
- Establish zero-shot baseline for WAA tasks
- Categorize failure modes (when demos help vs hurt)
- Validate evaluation infrastructure
- Provide decision data for Phase 1 investment

### 1.3 Success Criteria

**PROCEED to Phase 1** (>20pp improvement):
- Demo-conditioning shows large effect
- Fine-tuning worth pursuing ($5k investment)

**ANALYZE cost-benefit** (10-20pp improvement):
- Demo-conditioning shows medium effect
- Need deeper analysis before committing

**STOP fine-tuning** (<10pp improvement):
- Demo-conditioning insufficient
- Publish prompting results, explore alternatives

---

## 2. Methodology

### 2.1 Experimental Design

**Task Selection**:
- 20 tasks from 154 WAA tasks
- Stratified sampling: 5 domains × 4 tasks each
- Balanced difficulty: simple (5), medium (10), hard (5)
- Diverse first actions: click (8), type (6), keyboard (3), wait (3)

**Conditions**:
1. **Zero-shot baseline**: Task instruction only, no demo
2. **Demo-conditioned**: Task instruction + retrieved demo (top-1 from 154-demo library)

**Models**:
- Claude Sonnet 4.5 (Anthropic)
- GPT-4V (OpenAI)

**Trials**: 3 trials per task-model-condition (for statistical power)

**Total Runs**: 20 tasks × 2 models × 2 conditions × 3 trials = 240 runs

### 2.2 Evaluation Setup

**Infrastructure**:
- Adapter: [WAALiveAdapter / WAAMockAdapter]
- Demo retrieval: RetrievalAugmentedAgent (embedding-based, top-k=1)
- Demo library: 154 synthetic demos (generated via LLM)
- Evaluation harness: `evaluate_agent_on_benchmark()`

**Parameters**:
- Max steps: 15
- Temperature: 0.0 (deterministic)
- Action syntax: CLICK(x, y), TYPE(text), KEYBOARD(key), WAIT(seconds), DONE()

**Metrics**:
- Episode success (binary: 0/1, primary metric)
- Steps to completion (integer)
- Time to completion (seconds)
- First-action accuracy (binary: 0/1)

### 2.3 Statistical Analysis

**Tests**:
- McNemar's test (paired proportions, p < 0.05)
- Bootstrap confidence intervals (95% CI, 10,000 resamples)
- Effect size: Cohen's d, odds ratio

**Power Analysis**:
- Sample size: 60 paired samples (20 tasks × 3 trials)
- Effect size: 20pp (0.3 → 0.5 success rate)
- Power: 0.92 (sufficient for detecting medium-large effects)

---

## 3. Results

### 3.1 Overall Success Rates

| Condition | Claude Sonnet 4.5 | GPT-4V | Combined |
|-----------|-------------------|--------|----------|
| **Zero-shot** | X% (N/60) | Y% (N/60) | Z% (N/120) |
| **Demo-conditioned** | X% (N/60) | Y% (N/60) | Z% (N/120) |
| **Improvement** | +Xpp | +Ypp | +Zpp |
| **95% CI** | [Y, Z] | [Y, Z] | [Y, Z] |
| **p-value** | p = X | p = Y | p = Z |

**Statistical Significance**: [Yes/No] (p < 0.05 threshold)

**Effect Size**: Cohen's d = X ([small: 0.2-0.5 / medium: 0.5-0.8 / large: >0.8])

### 3.2 Efficiency Metrics

| Metric | Zero-shot (Claude) | Demo (Claude) | Zero-shot (GPT-4V) | Demo (GPT-4V) |
|--------|-------------------|---------------|-------------------|---------------|
| **Avg steps** | X ± Y | X ± Y | X ± Y | X ± Y |
| **Avg time (s)** | X ± Y | X ± Y | X ± Y | X ± Y |
| **First-action accuracy** | X% | Y% | X% | Y% |

**Key Findings**:
- [Finding 1]: Description
- [Finding 2]: Description
- [Finding 3]: Description

### 3.3 Per-Task Breakdown

**Top 5 Most Improved Tasks** (demo vs zero-shot):

| Task ID | Domain | Zero-shot | Demo | Improvement |
|---------|--------|-----------|------|-------------|
| [task_1] | [domain] | X% | Y% | +Zpp |
| [task_2] | [domain] | X% | Y% | +Zpp |
| [task_3] | [domain] | X% | Y% | +Zpp |
| [task_4] | [domain] | X% | Y% | +Zpp |
| [task_5] | [domain] | X% | Y% | +Zpp |

**Top 5 Least Improved Tasks** (or degraded):

| Task ID | Domain | Zero-shot | Demo | Improvement |
|---------|--------|-----------|------|-------------|
| [task_1] | [domain] | X% | Y% | +Zpp |
| [task_2] | [domain] | X% | Y% | +Zpp |
| [task_3] | [domain] | X% | Y% | +Zpp |
| [task_4] | [domain] | X% | Y% | +Zpp |
| [task_5] | [domain] | X% | Y% | +Zpp |

---

## 4. Failure Mode Analysis

### 4.1 Failure Categories

**Zero-Shot Failures** (N total):
1. **Coordinate precision errors** (X failures, Y%):
   - Description: Agent clicks/types at wrong coordinates
   - Examples: [task_1, task_2]
   - Demo helps? [Yes/No]

2. **Instruction misunderstanding** (X failures, Y%):
   - Description: Agent misinterprets task instruction
   - Examples: [task_1, task_2]
   - Demo helps? [Yes/No]

3. **Timeout/max steps exceeded** (X failures, Y%):
   - Description: Agent doesn't complete within 15 steps
   - Examples: [task_1, task_2]
   - Demo helps? [Yes/No]

4. **Application state errors** (X failures, Y%):
   - Description: App in wrong state, action fails
   - Examples: [task_1, task_2]
   - Demo helps? [Yes/No]

**Demo-Conditioned Failures** (N total):
1. **Demo over-fitting** (X failures, Y%):
   - Description: Agent follows demo too literally, wrong context
   - Examples: [task_1, task_2]

2. **Retrieval mismatch** (X failures, Y%):
   - Description: Retrieved demo not relevant to task
   - Examples: [task_1, task_2]

3. **Other** (X failures, Y%):
   - Description: Other failure modes
   - Examples: [task_1, task_2]

### 4.2 When Demos Help

**Scenarios where demo-conditioning improves success**:

1. **Multi-step sequences** (X% improvement):
   - Tasks requiring 5+ coordinated actions
   - Examples: [task_1, task_2]
   - Hypothesis: Demos provide action sequence template

2. **Precise coordinates** (X% improvement):
   - Tasks requiring exact click locations
   - Examples: [task_1, task_2]
   - Hypothesis: Demos anchor spatial reasoning

3. **Domain-specific workflows** (X% improvement):
   - Tasks with application-specific conventions
   - Examples: [task_1, task_2]
   - Hypothesis: Demos encode domain knowledge

### 4.3 When Demos Don't Help

**Scenarios where demo-conditioning shows no improvement or degrades**:

1. **Simple single-action tasks** (X% improvement):
   - Tasks solvable in 1-2 actions
   - Examples: [task_1, task_2]
   - Hypothesis: Demo overhead not needed

2. **Context-sensitive tasks** (X% improvement):
   - Tasks where demo context differs from eval
   - Examples: [task_1, task_2]
   - Hypothesis: Demo misleads agent

3. **Novel task variants** (X% improvement):
   - Tasks with no similar demo in library
   - Examples: [task_1, task_2]
   - Hypothesis: Retrieval fails to find relevant demo

---

## 5. Demo Quality Analysis

### 5.1 Retrieval Performance

**Top-1 Retrieval Accuracy**: X%
- Correct demo retrieved: N/240 runs
- Marginal demo retrieved: N/240 runs
- Incorrect demo retrieved: N/240 runs

**Retrieval Errors**:
- [Error type 1]: N occurrences
- [Error type 2]: N occurrences

### 5.2 Demo Format Adherence

**Synthetic Demos Validation**:
- Valid action syntax: X%
- Coherent reasoning: Y%
- Realistic coordinates: Z%

**Issues Found**:
- [Issue 1]: Description, frequency
- [Issue 2]: Description, frequency

---

## 6. Cost Analysis

### 6.1 Budget vs Actual

| Category | Budgeted | Actual | Variance |
|----------|----------|--------|----------|
| **API Costs** | | | |
| Claude Sonnet 4.5 | $75 | $X | $Y |
| GPT-4V | $210 | $X | $Y |
| **Infrastructure** | | | |
| Azure VM | $20 | $X | $Y |
| Storage | $5 | $X | $Y |
| **Contingency** | $90 | $X | $Y |
| **TOTAL** | **$400** | **$X** | **$Y** |

**Budget Efficiency**:
- Cost per run: $X (average)
- Under/over budget: $Y (Z%)

### 6.2 Cost Breakdown by Condition

| Condition | Claude | GPT-4V | Total |
|-----------|--------|--------|-------|
| Zero-shot | $X | $Y | $Z |
| Demo-conditioned | $X | $Y | $Z |

**Cost per success**: $X (zero-shot), $Y (demo-conditioned)

### 6.3 Lessons for Phase 1

**Cost Optimization Opportunities**:
- [Opportunity 1]: Estimated savings
- [Opportunity 2]: Estimated savings

**Budget Recommendations**:
- [Recommendation 1]
- [Recommendation 2]

---

## 7. Decision Analysis

### 7.1 Results Interpretation

**Improvement Magnitude**: +Xpp (95% CI: [Y, Z])

**Decision Threshold**:
- [X] **>20pp**: Demo-augmentation CLEARLY helps → PROCEED
- [ ] **10-20pp**: Demo-augmentation MARGINALLY helps → ANALYZE
- [ ] **<10pp**: Demo-augmentation INSUFFICIENT → STOP

**Statistical Significance**: p = X
- [X] **p < 0.05**: Statistically significant
- [ ] **p ≥ 0.05**: Not statistically significant

**Effect Size**: Cohen's d = X
- [X] **d > 0.8**: Large effect
- [ ] **d = 0.5-0.8**: Medium effect
- [ ] **d < 0.5**: Small effect

### 7.2 Decision Options

#### Option 1: PROCEED to Phase 1 (Training Infrastructure)

**Criteria**: >20pp improvement, p < 0.05, large effect size

**Next Steps**:
- [ ] Plan Phase 1 (4 weeks, $500 budget)
- [ ] Collect behavioral cloning dataset (50+ tasks)
- [ ] Implement LoRA fine-tuning pipeline
- [ ] Validate training infrastructure end-to-end

**Justification**:
- Demo-conditioning shows large, statistically significant effect in prompting
- Fine-tuning likely to amplify this benefit
- Investment justified ($5k for 20pp+ improvement)

**Timeline**: Phase 1-3 (6 months), publication target: NeurIPS/ICML 2026

#### Option 2: ANALYZE Cost-Benefit (Workshop Paper + Optional Fine-Tuning)

**Criteria**: 10-20pp improvement, p < 0.05, medium effect size

**Next Steps**:
- [ ] Write prompting results paper (workshop submission)
- [ ] Conduct detailed cost-benefit analysis for fine-tuning
- [ ] Explore alternative approaches (architectural changes, better demos)

**Justification**:
- Demo-conditioning shows moderate effect
- Fine-tuning may improve, but ROI unclear
- Publish prompting results first, decide fine-tuning later

**Timeline**: Workshop paper (3 months), fine-tuning decision deferred

#### Option 3: STOP Fine-Tuning (Publish Prompting Results)

**Criteria**: <10pp improvement OR p ≥ 0.05, small/no effect

**Next Steps**:
- [ ] Write prompting results paper (negative result or failure analysis)
- [ ] Explore architectural alternatives (tool use, multi-modal grounding)
- [ ] Defer fine-tuning indefinitely

**Justification**:
- Demo-conditioning insufficient in prompting
- Fine-tuning unlikely to overcome this limitation
- Publish findings, pivot to other approaches

**Timeline**: Workshop paper (3 months), pivot to new research direction

### 7.3 Recommended Decision

**Decision**: [PROCEED / ANALYZE / STOP]

**Reasoning**:
- [Justification based on results]
- [Cost-benefit analysis]
- [Strategic considerations]

**Confidence Level**: [High / Medium / Low]

**Risk Assessment**:
- Primary risk: [Risk description]
- Mitigation: [Mitigation plan]

---

## 8. Next Steps

### 8.1 Immediate (This Week)

**If PROCEED**:
- [ ] Allocate Phase 1 budget ($500)
- [ ] Define 50-task dataset for behavioral cloning
- [ ] Plan Phase 1 timeline (Weeks 3-6)
- [ ] Identify team members for training infrastructure

**If ANALYZE**:
- [ ] Start workshop paper draft (prompting results)
- [ ] Conduct cost-benefit analysis for fine-tuning
- [ ] Explore alternative demo generation methods

**If STOP**:
- [ ] Start workshop paper draft (negative result)
- [ ] Brainstorm architectural alternatives
- [ ] Update research roadmap

### 8.2 Short-Term (Next Month)

**If PROCEED**:
- [ ] Build training infrastructure (LoRA fine-tuning)
- [ ] Collect behavioral cloning dataset
- [ ] Validate training pipeline end-to-end
- [ ] Prepare for Phase 2 (fine-tuning experiments)

**If ANALYZE**:
- [ ] Submit workshop paper (deadline: ~July 2026)
- [ ] Prototype alternative approaches
- [ ] Revisit fine-tuning decision after workshop feedback

**If STOP**:
- [ ] Submit workshop paper (deadline: ~July 2026)
- [ ] Pivot to new research direction
- [ ] Archive Phase 0 results for future reference

### 8.3 Long-Term (6-12 Months)

**If PROCEED**:
- [ ] Complete Phase 2 (fine-tuning experiments, $5k budget)
- [ ] Complete Phase 3 (publication, main track submission)
- [ ] Target venue: NeurIPS/ICML/CHI 2027

**If ANALYZE or STOP**:
- [ ] Publish prompting results (workshop)
- [ ] Explore new research directions
- [ ] Reassess demo-augmentation approach in 12 months

---

## 9. Lessons Learned

### 9.1 Technical Lessons

**What Worked Well**:
- [Lesson 1]: Description
- [Lesson 2]: Description
- [Lesson 3]: Description

**What Could Be Improved**:
- [Lesson 1]: Description, improvement plan
- [Lesson 2]: Description, improvement plan
- [Lesson 3]: Description, improvement plan

### 9.2 Process Lessons

**Project Management**:
- [Lesson 1]: Description
- [Lesson 2]: Description

**Resource Planning**:
- [Lesson 1]: Description
- [Lesson 2]: Description

**Communication**:
- [Lesson 1]: Description
- [Lesson 2]: Description

### 9.3 Research Lessons

**Experimental Design**:
- [Lesson 1]: Description
- [Lesson 2]: Description

**Statistical Analysis**:
- [Lesson 1]: Description
- [Lesson 2]: Description

**Failure Modes**:
- [Lesson 1]: Description
- [Lesson 2]: Description

---

## 10. Conclusion

**Summary**: Phase 0 successfully measured demo-conditioning impact in prompting, providing decision data for fine-tuning investment.

**Key Findings**:
1. Demo-conditioning improves episode success rate by +Xpp (95% CI: [Y, Z])
2. Statistical significance achieved (p = X)
3. Effect size: Cohen's d = X (small/medium/large)
4. Demos help most for: [scenario 1, scenario 2, scenario 3]
5. Demos don't help for: [scenario 1, scenario 2, scenario 3]

**Decision**: [PROCEED / ANALYZE / STOP]

**Next Steps**: [Brief summary of next steps]

**Acknowledgments**: [Team members, advisors, resources used]

---

## Appendices

### Appendix A: Task List

**20 Selected Tasks**:
1. [task_id]: [domain], [difficulty], [first_action]
2. [task_id]: [domain], [difficulty], [first_action]
[... continue for all 20 tasks]

### Appendix B: Detailed Results

**Per-Task Results** (full table):
[Link to CSV file or attach as separate document]

### Appendix C: Failure Examples

**Example 1: Coordinate Precision Error**
- Task: [task_id]
- Condition: Zero-shot
- Screenshot: [link]
- Description: [details]

[... continue for representative examples]

### Appendix D: Demo Library

**Sample Demos**:
- [task_1]: [demo_file.txt]
- [task_2]: [demo_file.txt]
[... continue for representative demos]

### Appendix E: Statistical Analysis Code

**Analysis Scripts**:
- McNemar's test: `scripts/phase0_analysis.py`
- Bootstrap CI: `scripts/phase0_analysis.py`
- Effect sizes: `scripts/phase0_analysis.py`

### Appendix F: Budget Tracking

**Cost Tracking Data**:
[Link to budget tracking file or attach CSV]

---

**Document Version**: 1.0
**Status**: TEMPLATE
**To Be Completed**: Feb 2, 2026
**Decision Gate Meeting**: Feb 3, 2026
