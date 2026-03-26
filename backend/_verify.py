"""Final verification of data_agent.py"""
import re, ast, sys

path = r'app/graph/nodes/data_agent.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
print(f"Total lines: {len(lines)}")

# 1) Check syntax
try:
    ast.parse(content)
    print("PASS: Python syntax OK")
except SyntaxError as e:
    print(f"FAIL: Syntax error at line {e.lineno}: {e.msg}")
    sys.exit(1)

# 2) Required exports for workflow.py
required = ['data_react_node', 'data_synthesis_node']
for name in required:
    if f'async def {name}' in content:
        print(f"PASS: {name} defined")
    else:
        print(f"FAIL: {name} NOT defined!")

# 3) Required constants
for name in ['DATA_REACT_PROMPT', 'SYNTHESIS_PROMPT', 'DATA_AGENT_TOOLS']:
    pattern = rf'^{name}\s*='
    if re.search(pattern, content, re.MULTILINE):
        print(f"PASS: {name} defined")
    else:
        print(f"FAIL: {name} NOT defined at module level!")

# 4) Check imports match usage
used_schemas = re.findall(r'args_schema=(\w+)', content)
imported_schemas = re.findall(r'^\s+(\w+Input),?$', content, re.MULTILINE)
for schema in set(used_schemas):
    if schema in imported_schemas:
        print(f"PASS: {schema} imported")
    else:
        print(f"FAIL: {schema} used but NOT imported!")

# 5) Check no conflict markers remain
if '<<<<<<<' in content or '>>>>>>>' in content or '\n=======\n' in content:
    print("FAIL: Conflict markers still present!")
else:
    print("PASS: No conflict markers")

# 6) List all function definitions
print("\nFunction map:")
for i, line in enumerate(lines, 1):
    s = line.strip()
    if s.startswith('async def ') or (s.startswith('def ') and not line[0].isspace()):
        print(f"  L{i}: {s[:70]}")
    elif s.startswith('def ') and line.startswith('    def ') and 'def _invoke' not in s:
        pass  # skip nested

print("\nDone.")
