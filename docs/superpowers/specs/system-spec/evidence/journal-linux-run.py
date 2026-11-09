from pathlib import Path
import hashlib,importlib.metadata,json,platform,subprocess,sys,xml.etree.ElementTree as ET
import modelable.operations.compilation as compilation
root=Path('/candidate')
assert Path(compilation.__file__).resolve()==root/'cli/src/modelable/operations/compilation.py'
nodes=['tests/test_compilation_service.py::test_apply_rejects_changed_resolved_parent_even_with_same_bytes','tests/test_compilation_service.py::test_preview_rejects_symlink_that_escapes_workspace','tests/test_compilation_cleanup_outcome.py']
args=[sys.executable,'-m','pytest',*nodes,'-n','0','-q','-r','sR','--tb=short','--junitxml=/results/junit.xml','--basetemp=/tmp/recovery-pytest','-p','no:cacheprovider']
r=subprocess.run(args)
suites=ET.parse('/results/junit.xml').getroot()
result={'exit_code':r.returncode,**{k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ['tests','failures','errors','skipped']}}
paths=['cli/src/modelable/operations/compilation.py','cli/src/modelable/operations/file_transaction.py','cli/src/modelable/operations/compilation_audit.py','cli/tests/test_compilation_service.py','cli/tests/test_compilation_cleanup_outcome.py','cli/uv.lock']
data={'source_revision':'deb6d668f4f0b3d3bafe60c715e1d3e6904f1609','source_archive_sha256':'e3eb6392047fe5bd9332014d0722e6bf34c1bd924d65896676fdde7e5e641a75','source_export_command':['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', 'deb6d668f4f0b3d3bafe60c715e1d3e6904f1609', 'cli'],'python':sys.version,'platform':platform.platform(),'implementation_module':str(Path(compilation.__file__).resolve()),'cwd':'cli','command':args,'packages':{d.metadata['Name']:d.version for d in sorted(importlib.metadata.distributions(),key=lambda d:d.metadata['Name'].lower())},'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},'byte_convention':'Controlled LF Git archive; every retained source hash is compared with the immutable Git blob.','result':result}
Path('/results/environment.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
sys.exit(r.returncode if r.returncode else (0 if result['tests']==4 and all(result[k]==0 for k in ['failures','errors','skipped']) else 2))
