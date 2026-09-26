"""No-network SDK integration gates; expose only status and test identifiers."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

SDK = Path(__file__).resolve().parents[1]
CANDIDATE = SDK.parent
ROOT = CANDIDATE.parents[1]
mode, label = sys.argv[1:]
xml = CANDIDATE / (label + '.xml')
record = CANDIDATE / (label + '.json')
assert not xml.exists() and not record.exists()
env = {key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL'}}
env.update(PYTHONPATH=str(SDK), PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
           MODEL_AGENT_API_KEY='synthetic-offline-test', HF_HUB_OFFLINE='1',
           LITELLM_LOCAL_MODEL_COST_MAP='True', DO_NOT_TRACK='1', OTEL_SDK_DISABLED='true')
guard = SDK / 'sitecustomize.py'
assert not guard.exists()
guard.write_text((ROOT / '.codex/context-summary-stable-20260921/sitecustomize.py').read_text())
try:
    if mode == 'format':
        changed = ['veadk/context/'+name for name in ('runtime.py','manager.py','tool_results.py',
                   'retrieval.py','hybrid_retriever.py','_hybrid_index.py','history_retrieval.py','history_projection.py')]
        changed += ['tests/context/test_hybrid_index.py','tests/context/test_hybrid_integration.py','tests/context/test_hybrid_history.py']
        command = [sys.executable,'-m','ruff','format',*changed]
    elif mode == 'full':
        command = [sys.executable, str(SDK/'tests/run_context_compression_gate.py'),
                   '-q', '--junitxml', str(xml)]
    elif mode == 'regression':
        command = [sys.executable,'-m','pytest','-q','-p','no:cacheprovider','--tb=no',
                   '--show-capture=no','--junitxml',str(xml),
                   str(SDK/'tests/context/test_adaptive_retrieval.py')]
    else:
        assert mode == 'targeted'
        command = [sys.executable,'-m','pytest','-q','-p','no:cacheprovider','--tb=no',
                   '--show-capture=no','--junitxml',str(xml),
                   str(SDK/'tests/context/test_hybrid_index.py'),
                   str(SDK/'tests/context/test_hybrid_integration.py'),str(SDK/'tests/context/test_hybrid_history.py'),
                   str(SDK/'tests/context/test_hybrid_incremental.py'),str(SDK/'tests/context/test_long_history_evidence.py'),
                   str(SDK/'tests/context/test_retrieval_deadline.py'),str(SDK/'tests/context/test_query_focus.py'),str(SDK/'tests/context/test_fine_spans.py'),
                   str(SDK/'tests/context/test_hierarchical_retrieval.py'),
                   str(SDK/'tests/context/test_evidence_coverage.py'),
                   str(SDK/'tests/context/test_adaptive_retrieval.py')]
    p = subprocess.run(command, cwd=SDK, env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=850)
finally:
    guard.unlink()
cases = ET.parse(xml).getroot().findall('.//testcase') if xml.exists() else []
failed = [c for c in cases if c.find('failure') is not None or c.find('error') is not None]
result = {'exit_code':p.returncode, 'mode':mode, 'tests':len(cases), 'offline':True,
          'failures':[c.get('name') for c in failed],
          'failure_types':[(c.find('failure') if c.find('failure') is not None else c.find('error')).get('type') for c in failed],
          'skipped':sum(c.find('skipped') is not None for c in cases),
          'source_sha256':{str(p.relative_to(SDK)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in SDK.rglob('*.py') if '__pycache__' not in p.parts}}
record.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'}))
raise SystemExit(p.returncode)
