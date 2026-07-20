from pathlib import Path

path = Path('mobile/src/app/(operator)/pipeline.tsx')
text = path.read_text(encoding='utf-8')
old = """    const batchIdForAllAttempts = startingBatchId ?? newClientBatchId();
    let batchId = batchIdForAllAttempts;
"""
new = """    const batchIdForAllAttempts = startingBatchId ?? newClientBatchId();
    let batchId: string | null = batchIdForAllAttempts;
"""
if old not in text:
    raise SystemExit('batch ID type marker not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
