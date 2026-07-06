#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import validate_operator_smoke_workflow as validator


def expect_failure(workflow: str, expected: str) -> None:
    try:
        validator.validate(workflow)
    except SystemExit as exc:
        message = str(exc)
        if expected not in message:
            raise SystemExit(f'expected failure containing {expected!r}, got {message!r}')
        return
    raise SystemExit(f'expected validator failure containing {expected!r}')


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f'{label} missing tokens: {missing}')


def main() -> int:
    workflow = Path('.github/workflows/operator-smoke.yml').read_text(encoding='utf-8')
    validator.validate(workflow)

    pipeline_workflow = Path('.github/workflows/pipeline-run.yml').read_text(encoding='utf-8')
    requirements = Path('requirements.txt').read_text(encoding='utf-8')
    require_tokens(
        'pipeline runtime deps',
        pipeline_workflow,
        [
            'pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu',
            'from torchvision.ops import nms',
            'import lap',
            'lap.__version__',
            'torchvision.__version__',
            'nms.__name__',
        ],
    )
    require_tokens('requirements', requirements, ['torch>=2.0.0', 'torchvision>=0.15.0', 'lap>=0.5.12', 'ultralytics>=8.3.0'])

    run_tracked = Path('scripts/run_tracked.py').read_text(encoding='utf-8')
    selector_runtime = Path('pipeline/selector_candidate_runtime.py').read_text(encoding='utf-8')
    require_tokens(
        'selector candidate runtime install',
        run_tracked,
        [
            '_install_selector_candidate_runtime',
            'from pipeline.selector_candidate_runtime import install',
            '_install_selector_candidate_runtime()',
            'import pipeline.orchestrator as _orchestrator',
        ],
    )
    require_tokens(
        'selector candidate runtime evidence',
        selector_runtime,
        [
            'selector_candidate_events.json',
            'build_selector_candidate_events',
            'analyzer._parse_session = parse_and_capture',
            'write_selector_candidate_events',
        ],
    )

    expect_failure(workflow.replace('actions/upload-artifact@v4', 'actions/upload-artifact@v3'), 'actions/upload-artifact@v4')
    expect_failure(workflow.replace('if: always()', 'if: success()'), 'if: always()')
    expect_failure(workflow.replace('args=(', 'ARGS=""'), 'args=')
    expect_failure(workflow.replace('operator-smoke-report.md', 'smoke.md', 1), 'write and upload operator-smoke-report.md')

    print('Operator Smoke workflow validator contract checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
