# Phase 0: Demo-Augmentation Prompting Baseline Task Set

**Version**: 1.0
**Date**: 2026-01-18
**Total Tasks**: 20 (from 154-task WAA suite)
**Purpose**: Establish baseline performance for demo-conditioned prompting experiments

## Selection Criteria

1. **Domain Diversity**: Representative coverage of all major WAA domains
2. **Complexity Range**: Mix of simple (4-7 steps), medium (8-12 steps), complex (13+ steps)
3. **Clear Success**: Unambiguous success criteria for evaluation
4. **Common Workflows**: Real-world user tasks
5. **Demo Coverage**: All selected tasks have synthetic demos in `demo_library/synthetic_demos/`

## Task Distribution by Domain

| Domain | Count | Rationale |
|--------|-------|-----------|
| Notepad | 3 | Basic text editing (simple, medium, complex) |
| Browser | 4 | Web navigation and interaction (critical domain) |
| Office | 3 | Document/spreadsheet/presentation workflows |
| Settings | 3 | System configuration tasks |
| File Explorer | 4 | File management operations (critical domain) |
| Paint | 1 | Graphics manipulation |
| Clock | 1 | Utility application |
| Media | 1 | System controls |

**Total**: 20 tasks

## Complexity Distribution

| Complexity | Steps | Count | Task IDs |
|------------|-------|-------|----------|
| Simple | 4-7 | 6 | browser_4, media_3, notepad_1, paint_10, file_explorer_1, file_explorer_6 |
| Medium | 8-12 | 8 | browser_2, clock_2, file_explorer_3, file_explorer_9, notepad_3, office_1, settings_1, settings_3 |
| Complex | 13+ | 6 | browser_5, notepad_5, office_4, office_9, settings_2, browser_7 |

## Selected Tasks

### 1. notepad_1 - Open Notepad
**Domain**: notepad
**Complexity**: Simple (7 steps)
**Description**: Launch Notepad application from Start menu
**Success Criteria**: Notepad window is open and ready for text input
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/notepad_1.txt`
**Rationale**: Most basic Windows application launch workflow; tests Start menu navigation and app launching

**Key Actions**:
- CLICK (Start menu)
- TYPE (search query)
- CLICK (app selection)
- DONE

---

### 2. notepad_3 - Save file as file_3.txt
**Domain**: notepad
**Complexity**: Medium (11 steps)
**Description**: Save current Notepad document with specific filename
**Success Criteria**: File "file_3.txt" exists in the specified location
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/notepad_3.txt`
**Rationale**: Tests File > Save As dialog navigation, typing filename, confirming save

**Key Actions**:
- HOTKEY (Ctrl+S or File menu)
- TYPE (filename)
- CLICK (Save button)
- DONE

---

### 3. notepad_5 - Replace 'old text' with 'new text'
**Domain**: notepad
**Complexity**: Complex (16 steps)
**Description**: Use Find and Replace to change text in document
**Success Criteria**: All instances of "old text" replaced with "new text"
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/notepad_5.txt`
**Rationale**: Multi-step dialog interaction; tests Edit menu, Find/Replace dialog, typing in multiple fields

**Key Actions**:
- HOTKEY (Ctrl+H)
- TYPE (find text)
- TYPE (replace text)
- CLICK (Replace All)
- DONE

---

### 4. browser_2 - Search for 'sample query' on Google
**Domain**: browser
**Complexity**: Medium (11 steps)
**Description**: Navigate to Google and perform search
**Success Criteria**: Search results page displayed for "sample query"
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/browser_2.txt`
**Rationale**: Common web workflow; tests URL navigation, typing in web forms, Enter key

**Key Actions**:
- CLICK (address bar)
- TYPE (google.com)
- CLICK (search box)
- TYPE (query)
- HOTKEY (Return)
- DONE

---

### 5. browser_4 - Open a new tab
**Domain**: browser
**Complexity**: Simple (4 steps)
**Description**: Create new browser tab using keyboard shortcut
**Success Criteria**: New blank tab is active in browser
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/browser_4.txt`
**Rationale**: Tests keyboard shortcut usage (Ctrl+T); minimal steps for baseline

**Key Actions**:
- HOTKEY (Ctrl+T)
- WAIT
- DONE

---

### 6. browser_5 - Clear browsing history
**Domain**: browser
**Complexity**: Complex (18 steps)
**Description**: Access browser settings and clear browsing data
**Success Criteria**: Browsing history is cleared
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/browser_5.txt`
**Rationale**: Multi-level menu navigation; tests Settings > Privacy > Clear Data workflow

**Key Actions**:
- CLICK (menu button)
- CLICK (Settings)
- CLICK (Privacy)
- CLICK (Clear browsing data)
- CLICK (Clear data button)
- DONE

---

### 7. browser_7 - Download document.txt from example.com
**Domain**: browser
**Complexity**: Medium (13 steps)
**Description**: Navigate to URL and download file
**Success Criteria**: File "document.txt" downloaded to Downloads folder
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/browser_7.txt`
**Rationale**: Tests URL navigation, link clicking, download confirmation

**Key Actions**:
- CLICK (address bar)
- TYPE (URL)
- CLICK (download link)
- WAIT (download)
- DONE

---

### 8. office_1 - Create a new document
**Domain**: office
**Complexity**: Medium (10 steps)
**Description**: Launch Word/LibreOffice and create blank document
**Success Criteria**: New blank document window is open
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/office_1.txt`
**Rationale**: Office application launch; tests app search and new document creation

**Key Actions**:
- CLICK (Start)
- TYPE (word/writer)
- CLICK (app)
- CLICK (Blank document)
- DONE

---

### 9. office_4 - Insert a table with 3x4
**Domain**: office
**Complexity**: Complex (19 steps)
**Description**: Create 3-column by 4-row table in document
**Success Criteria**: Table with 3 columns and 4 rows exists in document
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/office_4.txt`
**Rationale**: Ribbon menu navigation; tests Insert > Table workflow with size specification

**Key Actions**:
- CLICK (Insert tab)
- CLICK (Table button)
- CLICK (table size selector)
- CLICK (Insert)
- DONE

---

### 10. office_9 - Apply formula in Excel
**Domain**: office
**Complexity**: Complex (15 steps)
**Description**: Enter data in cells and apply SUM formula
**Success Criteria**: Formula "=SUM(A1:A2)" in cell A3 displays correct result (30)
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/office_9.txt`
**Rationale**: Spreadsheet workflow; tests cell selection, typing values, formula syntax

**Key Actions**:
- CLICK (cell A1)
- TYPE (10)
- HOTKEY (Return)
- TYPE (20)
- HOTKEY (Return)
- TYPE (=SUM(A1:A2))
- HOTKEY (Return)
- DONE

---

### 11. settings_1 - Change display brightness
**Domain**: settings
**Complexity**: Medium (11 steps)
**Description**: Navigate to Display settings and adjust brightness slider
**Success Criteria**: Display brightness changed to new level
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/settings_1.txt`
**Rationale**: Settings app navigation; tests Start > Settings > System > Display workflow

**Key Actions**:
- CLICK (Start)
- CLICK (Settings)
- CLICK (System)
- CLICK (Display)
- DRAG (brightness slider)
- DONE

---

### 12. settings_2 - Connect to WiFi network
**Domain**: settings
**Complexity**: Complex (17 steps)
**Description**: Access network settings and connect to WiFi
**Success Criteria**: Connected to specified WiFi network
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/settings_2.txt`
**Rationale**: Multi-step configuration; tests Settings > Network > WiFi > Connect workflow with password entry

**Key Actions**:
- CLICK (Start)
- CLICK (Settings)
- CLICK (Network & Internet)
- CLICK (WiFi)
- CLICK (network name)
- TYPE (password)
- CLICK (Connect)
- DONE

---

### 13. settings_3 - Adjust sound volume
**Domain**: settings
**Complexity**: Medium (11 steps)
**Description**: Navigate to Sound settings and change volume
**Success Criteria**: System volume changed to new level
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/settings_3.txt`
**Rationale**: Settings workflow; tests Start > Settings > System > Sound path

**Key Actions**:
- CLICK (Start)
- CLICK (Settings)
- CLICK (System)
- CLICK (Sound)
- DRAG (volume slider)
- DONE

---

### 14. file_explorer_1 - Open File Explorer
**Domain**: file_explorer
**Complexity**: Simple (7 steps)
**Description**: Launch File Explorer from taskbar
**Success Criteria**: File Explorer window is open
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/file_explorer_1.txt`
**Rationale**: Basic app launch; tests taskbar icon clicking

**Key Actions**:
- CLICK (File Explorer icon)
- WAIT
- DONE

---

### 15. file_explorer_3 - Create new folder folder_3
**Domain**: file_explorer
**Complexity**: Medium (13 steps)
**Description**: Right-click to create new folder with specific name
**Success Criteria**: Folder named "folder_3" exists in current directory
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/file_explorer_3.txt`
**Rationale**: Context menu workflow; tests Right-click > New > Folder > Rename

**Key Actions**:
- RIGHT_CLICK (empty space)
- CLICK (New)
- CLICK (Folder)
- TYPE (folder_3)
- HOTKEY (Return)
- DONE

---

### 16. file_explorer_6 - Delete document.txt
**Domain**: file_explorer
**Complexity**: Complex (12 steps)
**Description**: Select file and delete it
**Success Criteria**: File "document.txt" no longer exists
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/file_explorer_6.txt`
**Rationale**: File management; tests file selection, Delete key, confirmation dialog

**Key Actions**:
- CLICK (file)
- HOTKEY (Delete)
- CLICK (Yes/Confirm)
- DONE

---

### 17. file_explorer_9 - Sort files by date
**Domain**: file_explorer
**Complexity**: Medium (11 steps)
**Description**: Change file sorting order to date modified
**Success Criteria**: Files displayed in date-modified order
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/file_explorer_9.txt`
**Rationale**: View customization; tests View menu > Sort by workflow

**Key Actions**:
- CLICK (View tab)
- CLICK (Sort by)
- CLICK (Date modified)
- DONE

---

### 18. paint_10 - Undo last action
**Domain**: paint
**Complexity**: Simple (4 steps)
**Description**: Use Ctrl+Z to undo previous action
**Success Criteria**: Last action is undone
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/paint_10.txt`
**Rationale**: Keyboard shortcut; tests universal undo command

**Key Actions**:
- HOTKEY (Ctrl+Z)
- WAIT
- DONE

---

### 19. clock_2 - Start a 5 minutes timer
**Domain**: clock
**Complexity**: Medium (12 steps)
**Description**: Open Clock app and set 5-minute timer
**Success Criteria**: Timer running with 5:00 countdown
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/clock_2.txt`
**Rationale**: Utility app workflow; tests app launch, tab navigation, input field interaction

**Key Actions**:
- CLICK (Start)
- TYPE (clock)
- CLICK (app)
- CLICK (Timer tab)
- TYPE (5)
- CLICK (Start)
- DONE

---

### 20. media_3 - Adjust volume to 50%
**Domain**: media
**Complexity**: Simple (6 steps)
**Description**: Use system tray to adjust volume to 50%
**Success Criteria**: System volume set to 50%
**Demo File**: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/media_3.txt`
**Rationale**: System tray interaction; tests volume control popup and slider manipulation

**Key Actions**:
- CLICK (volume icon in system tray)
- CLICK (volume slider at 50%)
- WAIT
- CLICK (outside to close)
- DONE

---

## Summary Statistics

**Total Tasks**: 20
**Total Domains**: 9
**Average Steps**: 10.75
**Step Range**: 4-19 steps

**Complexity Breakdown**:
- Simple (4-7 steps): 30% (6 tasks)
- Medium (8-12 steps): 40% (8 tasks)
- Complex (13-19 steps): 30% (6 tasks)

**Domain Coverage**:
- Notepad: 15% (3 tasks)
- Browser: 20% (4 tasks)
- Office: 15% (3 tasks)
- Settings: 15% (3 tasks)
- File Explorer: 20% (4 tasks)
- Other utilities: 15% (3 tasks - paint, clock, media)

## Expected Baseline Performance

Based on prior results (WAA_BASELINE_VALIDATION_PLAN.md):

**Without Demo**:
- First-action accuracy: ~33%
- Episode success: ~0%
- Average steps per task: ~8-10

**With Demo (Expected Improvement)**:
- First-action accuracy: ~100% (3x improvement)
- Episode success: ~40-60% (target based on demo guidance)
- Average steps per task: ~6-8 (more efficient paths)

## Usage

**Run Phase 0 evaluation**:
```bash
# Load task list
TASK_IDS=$(cat /Users/abrichr/oa/src/openadapt-evals/PHASE0_TASKS.txt | tr '\n' ',')

# Run with demo augmentation
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids $TASK_IDS \
    --demo-library /Users/abrichr/oa/src/openadapt-evals/demo_library

# Run without demo (control baseline)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids $TASK_IDS
```

**Individual task validation**:
```bash
# Test single task
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids notepad_1 \
    --demo /Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/notepad_1.txt
```

## Verification

All selected demos exist:
```bash
cd /Users/abrichr/oa/src/openadapt-evals
for task in $(cat PHASE0_TASKS.txt); do
    if [ ! -f "demo_library/synthetic_demos/${task}.txt" ]; then
        echo "MISSING: $task"
    else
        echo "OK: $task"
    fi
done
```

Expected output: 20 "OK" lines, 0 "MISSING" lines.

## Next Steps

1. **Verify demos**: Run validation script to ensure all demos are well-formed
2. **Baseline run**: Execute without demo to establish control metrics
3. **Demo-augmented run**: Execute with demo to measure improvement
4. **Analysis**: Compare first-action accuracy, episode success, efficiency
5. **Iteration**: Refine demos based on failure analysis if needed

## References

- Full task suite: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/demos.json`
- Demo library: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/`
- Validation plan: `/Users/abrichr/oa/src/openadapt-evals/WAA_BASELINE_VALIDATION_PLAN.md`
- Demo augmentation strategy: `/Users/abrichr/oa/src/openadapt-evals/DEMO_AUGMENTATION_STRATEGY.md`
