"""Generate transition VRMA then quickly test via Puppeteer."""
import subprocess, sys

pair = '105_13,105_32'
a, b = [p.strip() + '.vrma' if '.' not in p else p for p in pair.split(',')]
tx = f'tx_{a.replace(".vrma","")}_to_{b.replace(".vrma","")}.vrma'

# Generate
r = subprocess.run(f'python python_scripts/generate_transition_vrma.py vrma/{a} vrma/{b} -o vrma/{tx} --threshold 15 --fps 60', shell=True, capture_output=True, text=True)
if r.returncode != 0:
    print('GENERATE FAIL:', r.stderr)
    sys.exit(1)
print('Generated:', tx)

# Now run python test
r = subprocess.run(f'python python_scripts/test_transition.py vrma/{a} vrma/{tx} vrma/{b}', shell=True, capture_output=True, text=True)
for line in r.stdout.split('\n'):
    if 'PASS' in line or 'FAIL' in line or 'max boundary' in line or 'snap' in line.lower():
        print(line)
