"""Fix AgentConsole.vue merge conflicts"""

path = r'src/components/AgentConsole.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Conflict 1: imports - keep both
old1 = """<<<<<<< HEAD
import { marked } from 'marked'

import { useDataRangeStore } from '@/stores/dataRangeStore'
=======
import { useReportStore } from '@/stores/reportStore'
import type { ReportSection } from '@/stores/reportStore'
>>>>>>> origin/feat/back"""

new1 = """import { marked } from 'marked'

import { useDataRangeStore } from '@/stores/dataRangeStore'
import { useReportStore } from '@/stores/reportStore'
import type { ReportSection } from '@/stores/reportStore'"""

if old1 in content:
    content = content.replace(old1, new1)
    print("Fix 1: Merged import blocks")
else:
    print("Fix 1: SKIP - not found")

# Conflict 2: store assignments - keep both
old2 = """<<<<<<< HEAD
const dataRangeStore = useDataRangeStore()
=======
const reportStore = useReportStore()
>>>>>>> origin/feat/back"""

new2 = """const dataRangeStore = useDataRangeStore()
const reportStore = useReportStore()"""

if old2 in content:
    content = content.replace(old2, new2)
    print("Fix 2: Merged store assignments")
else:
    print("Fix 2: SKIP - not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
remaining = content.count('<<<<<<<')
print(f"Remaining conflicts: {remaining}")
print(f"Final lines: {len(content.splitlines())}")
