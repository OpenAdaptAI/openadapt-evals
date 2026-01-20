# PM Claude Code Task Search Results

**Date**: 2026-01-18
**Search Query**: Previous background agent investigating GitHub Projects and PM Claude Code meta approach
**Status**: FOUND

---

## 1. Found / Not Found

**FOUND**: Yes, the task was identified and documented.

---

## 2. Task Details

### Task Identification

- **Agent ID**: Not a background agent - this was research analysis work
- **Date Created**: January 16, 2026
- **Task Type**: Research and analysis document
- **Original Question**: Whether to use some sort of meta approach involving GitHub projects and a PM Claude Code

### Deliverables Located

**Primary Document**: `/Users/abrichr/oa/src/openadapt-evals/docs/research/tmux-orchestrator-analysis.md`
- Comprehensive 358-line analysis document
- Evaluates multi-agent orchestration approaches for OpenAdapt development

**Follow-up Document**: `/Users/abrichr/oa/src/openadapt-evals/docs/research/deferred-work.md`
- Notes CCPM for future evaluation
- Clarifies the actual use case vs. initial misunderstanding

---

## 3. Results - What Were the Findings/Recommendations?

### Executive Summary (from the analysis)

**Key Finding**: The analysis evaluated whether to adopt orchestration tools for coordinating Claude Code agents across OpenAdapt's multi-package ecosystem (openadapt-ml, openadapt-evals, openadapt-viewer, etc.).

### Tools Evaluated

| Tool | Purpose | Verdict |
|------|---------|---------|
| **Tmux-Orchestrator** | Multi-agent coordination via tmux sessions | ❌ NOT RECOMMENDED |
| **CCPM (Claude Code PM)** | GitHub Issues-based PM system for Claude Code | ✅ RECOMMENDED for evaluation |
| **parallel-claude** | Simple multi-repo spawning with iTerm2 | ⚠️ Consider (macOS only) |
| **Claude Code --add-dir** | Built-in multi-directory context | ✅ Use for analysis |

### Primary Recommendation: CCPM (Claude Code PM)

**Repository**: https://github.com/automazeio/ccpm

**Why CCPM was recommended**:
1. **GitHub Integration**: Uses GitHub Issues as the coordination database
2. **Git Worktrees**: Enables parallel execution without branch conflicts
3. **PRD-to-Task Decomposition**: Spec-driven development approach
4. **Claude Code Integration**: Works with existing CLAUDE.md files
5. **Team Visibility**: All coordination visible to team members (vs. hidden tmux sessions)

**Example Workflow**:
```bash
/pm:prd-new          # Create PRD for new feature
/pm:epic-decompose   # Break into tasks across packages
/pm:epic-sync        # Push to GitHub Issues with labels
/pm:issue-start      # Agents work on issues in parallel
```

**Reported Capabilities**:
- Supports 5-8 parallel tasks simultaneously
- Full visibility for team members
- Easy handoffs between agents

### Why Tmux-Orchestrator was NOT recommended

**Strengths**:
- Session persistence
- Hierarchical agent structure
- Self-scheduling capabilities

**Critical Weaknesses**:
- ❌ No GitHub integration (our primary workflow)
- ❌ macOS-only shell scripts
- ❌ No uv package manager support
- ❌ Fragile inter-agent messaging
- ❌ Limited team visibility (hidden tmux sessions)
- ❌ No parallelism control or resource limits

### Hybrid Strategy Recommendation

**For Cross-Package Development**:

1. **Use Claude Code `--add-dir`** for analysis and planning across packages
2. **Use CCPM** for task decomposition and GitHub-based tracking
3. **Use parallel-claude** (or manual tmux sessions) for parallel execution

**Example Workflow**:
```bash
# 1. Analyze scope with multi-directory context
claude --add-dir /Users/abrichr/oa/src/openadapt-ml \
       --add-dir /Users/abrichr/oa/src/openadapt-evals \
       --add-dir /Users/abrichr/oa/src/openadapt-grounding

# 2. Create PRD and decompose with CCPM
/pm:prd-new "Add WebArena benchmark support"
/pm:epic-decompose

# 3. Execute in parallel
# - Option A: parallel-claude for automated spawning
# - Option B: Manual tmux sessions with existing CLI commands
```

---

## 4. Location - Where Are Results Documented?

### Primary Documentation

**Main Analysis Document**:
- **Path**: `/Users/abrichr/oa/src/openadapt-evals/docs/research/tmux-orchestrator-analysis.md`
- **Size**: 358 lines
- **Sections**:
  - Executive Summary
  - What is Tmux-Orchestrator?
  - Applicability to OpenAdapt Ecosystem
  - Critical Evaluation
  - Alternatives Analysis (CCPM, parallel-claude, --add-dir)
  - Recommendations
  - Comparison Matrix

**Follow-up Notes**:
- **Path**: `/Users/abrichr/oa/src/openadapt-evals/docs/research/deferred-work.md`
- **Note**: Clarifies that CCPM is noted for future evaluation
- **Important clarification**: "The earlier Tmux-Orchestrator analysis incorrectly framed it as a runtime substrate. The actual question was about using it for **development workflow** - orchestrating Claude instances during development."

### Reference Links in Documentation

- [Tmux-Orchestrator GitHub](https://github.com/Jedward23/Tmux-Orchestrator)
- [CCPM (Claude Code PM)](https://github.com/automazeio/ccpm)
- [parallel-claude](https://github.com/saadnvd1/parallel-claude)
- [Claude Code --add-dir Documentation](https://claudelog.com/faqs/--add-dir/)
- [Polyrepo Synthesis with Claude Code](https://rajiv.com/blog/2025/11/30/polyrepo-synthesis-synthesis-coding-across-multiple-repositories-with-claude-code-in-visual-studio-code/)

---

## 5. Status - Was Task Completed? Actionable Outcomes?

### Completion Status

✅ **COMPLETED** - Research and analysis finished on January 16, 2026

### Actionable Outcomes

**Immediate Actions Recommended** (from the analysis):

1. ❌ **No adoption of Tmux-Orchestrator** at this time
2. ⚠️ **Experiment with CCPM** on a small feature to evaluate fit
3. ⚠️ **Document multi-repo workflow** for team members using existing tools
4. ⚠️ **Consider parallel-claude** if macOS-only is acceptable for developer tooling

### Implementation Status

**Current Status**: DEFERRED FOR FUTURE EVALUATION

From `deferred-work.md`:
> **Status**: Noted for future evaluation
>
> **Potential use case**: Multi-agent orchestration for developing OpenAdapt components across repositories. CCPM uses GitHub Issues-based coordination which could be valuable for:
> - Coordinating work across openadapt-evals, openadapt-ml, openadapt-viewer packages
> - Automating release workflows
> - Managing dependent PRs across repos

**When to Revisit**:
- When coordinating complex work across multiple OpenAdapt packages
- When managing dependent PRs across repos
- When automating release workflows
- When parallel development across packages becomes a bottleneck

### No Evidence of CCPM Adoption

After searching the codebase:
- No CCPM installation found
- No GitHub Projects integration configured
- No PRD workflow implemented
- No automated task decomposition system

**Conclusion**: The analysis was completed and recommendations were made, but the tooling has **NOT been adopted** yet. It remains as a **future option** when multi-package coordination becomes necessary.

---

## 6. Comparison Matrix (from Analysis)

| Feature | Tmux-Orchestrator | CCPM | parallel-claude | --add-dir |
|---------|------------------|------|-----------------|-----------|
| GitHub Integration | No | Yes (native) | Limited | No |
| Parallel Execution | Yes | Yes | Yes | No |
| uv Compatibility | Manual | Requires setup | Manual | Native |
| Team Visibility | Low (tmux) | High (GitHub) | Low (local) | N/A |
| Setup Complexity | High | Medium | Low | None |
| Cross-Platform | Partial | Yes | macOS only | Yes |
| Orchestration | Yes | Yes | No | No |
| Our Current Tools | Incompatible | Compatible | Partially | Compatible |

---

## 7. Context & Background

### The Original Question

The analysis was motivated by a need to coordinate Claude Code agents across OpenAdapt's multi-package architecture:

**OpenAdapt Package Structure** (7+ interrelated packages):
- `openadapt-ml` - ML engine, VLM adapters, training pipeline
- `openadapt-capture` - Screen capture and event recording
- `openadapt-evals` - Benchmark evaluation infrastructure
- `openadapt-viewer` - Visualization and replay tools
- `openadapt-retrieval` - Demo retrieval for RAG agents
- `openadapt-grounding` - UI element localization
- `openadapt-new` - New core orchestration

**Problem**: How to coordinate development work that spans multiple packages?

**Answer**: CCPM recommended for GitHub-based orchestration, but not yet implemented.

---

## 8. Why This Wasn't Found Initially

### Search Challenges

1. **Not a Background Agent**: This was research analysis work, not a long-running background task
2. **No Agent ID**: Not tracked in the background agent system
3. **Specific File Location**: Buried in `/docs/research/` subdirectory
4. **Different Terminology**: Searched for "GitHub projects" but document uses "GitHub Issues"

### How It Was Found

Located via:
1. Grep search for "pm.*claude" in .md files
2. Found references in `tmux-orchestrator-analysis.md`
3. Cross-referenced with `deferred-work.md`

---

## 9. Recommendations

### If You Want to Adopt CCPM

1. **Read the Analysis**: Start with `/Users/abrichr/oa/src/openadapt-evals/docs/research/tmux-orchestrator-analysis.md`
2. **Visit CCPM Repository**: https://github.com/automazeio/ccpm
3. **Run Small Experiment**: Test CCPM on a single-package feature first
4. **Evaluate Fit**: Assess whether GitHub Issues-based workflow fits team practices
5. **Document Workflow**: Update team documentation if adopted

### If You Don't Want to Adopt CCPM

**Alternative Approaches**:
1. **Continue with current workflow**: Manual coordination via GitHub PRs
2. **Use Claude Code --add-dir**: For cross-package analysis
3. **Use parallel-claude**: For simple multi-repo spawning (macOS only)
4. **Custom scripting**: Build lightweight coordination scripts as needed

---

## 10. Related Documentation

### Additional Context Files

- **Project Status**: `/Users/abrichr/oa/src/STATUS.md`
- **Session Summary**: `/Users/abrichr/oa/src/SESSION_SUMMARY_2026-01-18.md`
- **CLAUDE.md files**: Each repository has development guidelines

### Other Research Documents

Located in `/Users/abrichr/oa/src/openadapt-evals/docs/research/`:
- `tmux-orchestrator-analysis.md` - Full orchestration analysis
- `deferred-work.md` - Items deferred for future consideration
- `legacy-transition-plan.md` - Other architectural decisions

---

## Summary

**Question**: "A while back we launched a background agent to report on whether to use some sort of meta approach involving GitHub projects and a PM Claude Code. What was the result of that task?"

**Answer**:

The research was completed on January 16, 2026. The recommendation was:

✅ **RECOMMENDED**: CCPM (Claude Code PM) - A GitHub Issues-based project management system for coordinating Claude Code agents across multiple repositories.

❌ **NOT RECOMMENDED**: Tmux-Orchestrator - Too many incompatibilities with existing tools and workflows.

**Current Status**: Analysis complete, tooling NOT yet adopted, noted for future evaluation when multi-package coordination becomes necessary.

**Documents**:
- `/Users/abrichr/oa/src/openadapt-evals/docs/research/tmux-orchestrator-analysis.md`
- `/Users/abrichr/oa/src/openadapt-evals/docs/research/deferred-work.md`

**CCPM Repository**: https://github.com/automazeio/ccpm
