#!/usr/bin/env python3
from pathlib import Path

path = Path('docs/app-pipeline-audit.md')
text = path.read_text(encoding='utf-8')
old = '- [ ] R2 CORS on the exact mobile origin/build exposes the part `ETag` header to the client.'
new = '- [ ] The exact installed React Native client can read the returned part `ETag`; configure R2 CORS to expose `ETag` only for any browser-based upload client.'
count = text.count(old)
if count != 1:
    raise SystemExit(f'expected one stale ETag audit sentence, found {count}')
text = text.replace(old, new)
if old in text or text.count(new) != 1:
    raise SystemExit('ETag audit correction did not apply exactly once')
path.write_text(text, encoding='utf-8')
print('Audit ETag client wording corrected')
