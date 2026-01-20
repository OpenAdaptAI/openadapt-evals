# Phase 0 Documentation Index

**Project**: Demo-Augmentation Prompting Baseline
**Timeline**: Jan 20 - Feb 2, 2026 (2 weeks)
**Budget**: $400
**Status**: Ready for launch

---

## Quick Navigation

**Start here**: [`PHASE0_QUICKSTART.md`](./PHASE0_QUICKSTART.md) - Quick start guide

**Full details**: [`PHASE0_PROJECT_PLAN.md`](./PHASE0_PROJECT_PLAN.md) - Comprehensive project plan

**Daily tracking**: [`PHASE0_PROGRESS.md`](./PHASE0_PROGRESS.md) - Daily progress tracker

---

## Documentation Structure

### Planning & Overview

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **PHASE0_QUICKSTART.md** | Quick start guide | First time setup, daily reference |
| **PHASE0_PROJECT_PLAN.md** | Comprehensive 2-week plan | Detailed planning, decision gates |
| **PHASE0_INDEX.md** | This file - navigation hub | Finding specific documents |

### Progress Tracking

| Document | Purpose | Update Frequency |
|----------|---------|------------------|
| **PHASE0_PROGRESS.md** | Daily progress tracker | Daily (end of day) |
| **PHASE0_STANDUP.md** | Daily standup logs | Daily (start of day) |
| **PHASE0_WEEKLY_REVIEW.md** | Weekly review templates | Weekly (Sat/Sun) |

### Final Deliverables

| Document | Purpose | When to Fill |
|----------|---------|--------------|
| **PHASE0_FINAL_REPORT.md** | Final report template | Feb 1-2, 2026 |

### Scripts & Tools

| Script | Purpose | Usage |
|--------|---------|-------|
| **scripts/phase0_runner.py** | Batch evaluation runner | Run experiments |
| **scripts/phase0_budget.py** | Budget tracker | Monitor costs |
| **scripts/phase0_dashboard.py** | Progress dashboard | Monitor progress |

---

## Workflows by Role

### Research Lead

**Daily**:
1. Review [`PHASE0_PROGRESS.md`](./PHASE0_PROGRESS.md) - Check overnight runs
2. Check budget: `python scripts/phase0_budget.py`
3. Monitor dashboard: `python scripts/phase0_dashboard.py`
4. Update [`PHASE0_STANDUP.md`](./PHASE0_STANDUP.md)

**Weekly**:
1. Fill in [`PHASE0_WEEKLY_REVIEW.md`](./PHASE0_WEEKLY_REVIEW.md)
2. Generate budget report: `python scripts/phase0_budget.py --report`
3. Review with team

**End of Phase 0**:
1. Complete [`PHASE0_FINAL_REPORT.md`](./PHASE0_FINAL_REPORT.md)
2. Prepare decision gate presentation
3. Make go/no-go decision

### Engineer

**Setup**:
1. Follow [`PHASE0_QUICKSTART.md`](./PHASE0_QUICKSTART.md)
2. Generate task set: `python scripts/phase0_runner.py --create-tasks`
3. Test infrastructure: `python scripts/phase0_runner.py --dry-run`

**Week 1** (Zero-shot):
1. Run baseline: `python scripts/phase0_runner.py --condition zero-shot --tasks phase0_tasks.json`
2. Monitor: `python scripts/phase0_dashboard.py --watch`
3. Update progress: [`PHASE0_PROGRESS.md`](./PHASE0_PROGRESS.md)

**Week 2** (Demo-conditioned):
1. Run demo runs: `python scripts/phase0_runner.py --condition demo-conditioned --tasks phase0_tasks.json`
2. Monitor: `python scripts/phase0_dashboard.py --watch`
3. Update progress: [`PHASE0_PROGRESS.md`](./PHASE0_PROGRESS.md)

### Analyst

**Week 1**:
1. Review zero-shot results
2. Categorize failure modes
3. Document in [`PHASE0_PROGRESS.md`](./PHASE0_PROGRESS.md)

**Week 2**:
1. Compare zero-shot vs demo-conditioned
2. Run statistical tests (McNemar's, bootstrap CI)
3. Fill in results section of [`PHASE0_FINAL_REPORT.md`](./PHASE0_FINAL_REPORT.md)

---

## File Organization

```
openadapt-evals/
├── PHASE0_PROJECT_PLAN.md          # Comprehensive plan (14K)
├── PHASE0_QUICKSTART.md            # Quick start guide (8.6K)
├── PHASE0_INDEX.md                 # This file - navigation
├── PHASE0_PROGRESS.md              # Daily tracker (9.1K)
├── PHASE0_STANDUP.md               # Daily standups (8.2K)
├── PHASE0_WEEKLY_REVIEW.md         # Weekly reviews (8.6K)
├── PHASE0_FINAL_REPORT.md          # Final report template (16K)
│
├── scripts/
│   ├── phase0_runner.py            # Batch runner (13K)
│   ├── phase0_budget.py            # Budget tracker (12K)
│   └── phase0_dashboard.py         # Dashboard (13K)
│
├── phase0_tasks.json               # Generated: 20-task set
├── phase0_budget.json              # Generated: budget data
├── phase0_results_*.json           # Generated: results
└── phase0_dashboard.html           # Generated: HTML dashboard
```

---

## Key Milestones

### Week 1 (Jan 20-26)

- [x] Day 1-2: Setup and infrastructure testing
- [ ] Day 3-5: Run 120 zero-shot evaluations
- [ ] Day 6-7: Initial analysis

### Week 2 (Jan 27 - Feb 2)

- [ ] Day 8-10: Run 120 demo-conditioned evaluations
- [ ] Day 11-12: Statistical analysis
- [ ] Day 13-14: Final report and decision gate

### Decision Gate (Feb 3)

- [ ] Present results
- [ ] Make go/no-go decision for Phase 1
- [ ] Update project roadmap

---

## Decision Criteria Quick Reference

| Improvement | Decision | Next Action |
|-------------|----------|-------------|
| **>20pp** | **PROCEED** | Phase 1: Training infrastructure ($500, 4 weeks) |
| **10-20pp** | **ANALYZE** | Workshop paper + cost-benefit analysis |
| **<10pp** | **STOP** | Publish prompting results, defer fine-tuning |

**Thresholds**:
- Statistical significance: p < 0.05 (McNemar's test)
- Effect size: Cohen's d (small: 0.2-0.5, medium: 0.5-0.8, large: >0.8)
- Budget: Must stay within $400

---

## Common Tasks

### Generate Task Set
```bash
python scripts/phase0_runner.py --create-tasks
```

### Run Zero-Shot Baseline
```bash
python scripts/phase0_runner.py --condition zero-shot --tasks phase0_tasks.json
```

### Run Demo-Conditioned
```bash
python scripts/phase0_runner.py --condition demo-conditioned --tasks phase0_tasks.json
```

### Monitor Progress
```bash
python scripts/phase0_dashboard.py --watch
```

### Check Budget
```bash
python scripts/phase0_budget.py
```

### Generate Reports
```bash
python scripts/phase0_budget.py --report
python scripts/phase0_dashboard.py --html
```

---

## Related Documentation

**Research Strategy**:
- [`DEMO_AUGMENTATION_STRATEGY.md`](./DEMO_AUGMENTATION_STRATEGY.md) - Overall research strategy

**Infrastructure**:
- [`demo_library/synthetic_demos/README.md`](./demo_library/synthetic_demos/README.md) - Demo library
- [`WAA_BASELINE_VALIDATION_PLAN.md`](./WAA_BASELINE_VALIDATION_PLAN.md) - WAA integration
- [`COST_TRACKING_DEMO.md`](./COST_TRACKING_DEMO.md) - Cost tracking

**Project Management**:
- [`README.md`](./README.md) - Main project README
- [`CHANGELOG.md`](./CHANGELOG.md) - Project changelog

---

## Support & Troubleshooting

**Common Issues**:

1. **Budget alerts**: See [`PHASE0_QUICKSTART.md`](./PHASE0_QUICKSTART.md) troubleshooting section
2. **Failed runs**: Check WAA server status, review failure modes
3. **Infrastructure issues**: See [`PHASE0_PROJECT_PLAN.md`](./PHASE0_PROJECT_PLAN.md) risk management

**Getting Help**:
- Check this index for relevant documentation
- Review [`PHASE0_QUICKSTART.md`](./PHASE0_QUICKSTART.md) for common commands
- Consult [`PHASE0_PROJECT_PLAN.md`](./PHASE0_PROJECT_PLAN.md) for detailed procedures

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-18 | Initial creation - comprehensive Phase 0 tracking system |

---

**Last Updated**: 2026-01-18
**Status**: Ready for launch
**Next Review**: Jan 20, 2026 (Day 1)
