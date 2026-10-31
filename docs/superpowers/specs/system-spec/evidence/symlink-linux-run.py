from pathlib import Path
import hashlib,importlib.metadata,json,platform,subprocess,sys,xml.etree.ElementTree as ET
nodes=['tests/test_compilation_service.py::test_apply_rejects_changed_resolved_parent_even_with_same_bytes', 'tests/test_compilation_service.py::test_preview_rejects_symlink_that_escapes_workspace']
args=[sys.executable,'-m','pytest',*nodes,'-n','0','-q','-r','a','--tb=short','--junitxml=/results/symlink-junit.xml','--basetemp=/tmp/symlink-pytest','-p','no:cacheprovider']
r=subprocess.run(args)
result={'exit_code':r.returncode}
if Path('/results/symlink-junit.xml').exists():
    suites=ET.parse('/results/symlink-junit.xml').getroot()
    result.update({k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ['tests','failures','errors','skipped']})
paths=['cli/src/modelable/operations/compilation.py','cli/src/modelable/operations/file_transaction.py','cli/src/modelable/operations/compilation_audit.py','cli/tests/test_compilation_service.py','cli/uv.lock']
data={'source_revision':'8de5b55bf07cff4a619c6ae25f2c3368290d310b','source_archive_sha256':'ddc6cfb0bda3d562f052aa050a0266baaf9fcfb8a7a505de6bd9085546123431','python':sys.version,'platform':platform.platform(),'cwd':'cli','command':args,'packages':{d.metadata['Name']:d.version for d in sorted(importlib.metadata.distributions(),key=lambda d:d.metadata['Name'].lower())},'source_sha256':{p:hashlib.sha256((Path('/source')/p).read_bytes()).hexdigest() for p in paths},'byte_convention':'Exact bytes extracted by git archive; Git-normalized LF, not Windows checkout bytes.','result':result}
Path('/results/environment.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
sys.exit(r.returncode if r.returncode else (0 if result.get('tests')==2 and all(result.get(k)==0 for k in ['failures','errors','skipped']) else 2))
