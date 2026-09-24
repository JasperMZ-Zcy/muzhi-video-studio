from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parents[1]
source=root/'vendor/editorial-magazine-explainer-producer/SKILL.md'
catalog=json.loads((root/'assets/critical-rules.json').read_text(encoding='utf-8'))
lines=source.read_text(encoding='utf-8-sig').splitlines();start=lines.index('## 一票否决')
actual=[(n+1,line[2:]) for n,line in enumerate(lines) if n>start and line.startswith('- ')]
assert len(actual)==len(catalog['vetoes'])
for (line,text),item in zip(actual,catalog['vetoes']):
 assert item['source_line']==line and item['text']==text
 assert item['enforcement'] and all((root/p).is_file() for p in item['references'])
assert catalog['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
print(json.dumps({'original_vetoes':len(actual),'preserved':len(catalog['vetoes']),'missing':0,'references_exist':True,'note':'coverage checks rule preservation, not actual visual quality'},ensure_ascii=False))
