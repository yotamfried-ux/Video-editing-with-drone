#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
            'Falling back to PyPI for torch/torchvision',
            'pip install torch torchvision --retries 5 --timeout 120',
            'from torchvision.ops import nms',
            'import lap',
            'lap.__version__',
            'torchvision.__version__',
            'nms.__name__',
        ],
    )
    require_tokens('requirements', requirements, ['torch>=2.0.0', 'torchvision>=0.15.0', 'lap>=0.5.12', 'ultralytics>=8.3.0'])

    run_tracked = Path('scripts/run_tracked.py').read_text(encoding='utf-8')
    bootstrap = Path('pipeline/bootstrap.py').read_text(encoding='utf-8')
    selector_runtime = Path('pipeline/selector_candidate_runtime.py').read_text(encoding='utf-8')
    draft_diagnostics = Path('pipeline/draft_diagnostics.py').read_text(encoding='utf-8')
    require_tokens(
        'production canonical bootstrap',
        run_tracked,
        [
            'from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches',
            'install_pre_orchestrator_patches()',
            'import pipeline.orchestrator as _orchestrator',
            'install_post_orchestrator_patches()',
        ],
    )
    require_tokens(
        'canonical selector and context runtime install',
        bootstrap,
        [
            'pipeline.selector_candidate_runtime',
            'pipeline.context_qa_long_video',
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
    require_tokens(
        'draft metadata uniqueness runtime',
        draft_diagnostics,
        [
            '_unique_draft_name',
            '_metadata_names',
            'orchestrator._safe_draft_name = unique_safe_draft_name',
            'used_names.update(_metadata_names(config.REEL_METADATA_FILE))',
        ],
    )

    from pipeline.draft_diagnostics import _unique_draft_name
    used: set[str] = set()
    first = _unique_draft_name('DRAFT_same_20260706.mp4', used)
    second = _unique_draft_name('DRAFT_same_20260706.mp4', used)
    third = _unique_draft_name('DRAFT_same_20260706.mp4', used)
    if first != 'DRAFT_same_20260706.mp4' or second != 'DRAFT_same_20260706_02.mp4' or third != 'DRAFT_same_20260706_03.mp4':
        raise SystemExit(f'draft name uniqueness failed: {first}, {second}, {third}')

    expect_failure(workflow.replace('actions/upload-artifact@v4', 'actions/upload-artifact@v3'), 'actions/upload-artifact@v4')
    expect_failure(workflow.replace('if: always()', 'if: success()'), 'if: always()')
    expect_failure(workflow.replace('args=(', 'ARGS=""'), 'args=')
    expect_failure(workflow.replace('operator-smoke-report.md', 'smoke.md', 1), 'write and upload operator-smoke-report.md')

    print('Operator Smoke workflow validator contract checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
