"""Compare baseline and candidate using the same calls and ALSA configuration."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from compatibility_probe import CompatibilityProbe


@pytest.fixture(scope='module')
def revision_results():
    """Execute each revision in a fresh interpreter to isolate PortAudio state."""
    baseline = os.environ.get('SOUNDDEVICE_BASELINE_PATH')
    if not baseline:
        pytest.skip('Set SOUNDDEVICE_BASELINE_PATH to built baseline src/')
    script = Path(__file__).with_name('compatibility_probe.py')
    results = []
    for path in (baseline, None):
        env = os.environ.copy()
        if path is None:
            env.pop('PYTHONPATH', None)
        else:
            env['PYTHONPATH'] = path
        completed = subprocess.run(
            [sys.executable, str(script)], env=env, text=True,
            capture_output=True, check=True, timeout=60)
        results.append(json.loads(completed.stdout))
    assert results[0]['module'] != results[1]['module']
    return results[0]['results'], results[1]['results']


@pytest.mark.parametrize('number,case', list(enumerate(CompatibilityProbe.cases())))
def test_same_public_calls_across_revisions(number, case, revision_results):
    """Preserve successful calls and explicitly account for changed errors."""
    baseline, candidate = (results[number] for results in revision_results)
    if case['operation'] == 'check_ignored_latency':
        assert baseline['status'] == 'error'
        assert baseline['type'] == 'TypeError'
        assert candidate == {'status': 'ok'}
    elif case.get('invalid') == 'device':
        assert baseline == {'status': 'error', 'type': 'PortAudioError',
                            'args': ['Error querying device 9999']}
        assert candidate == {
            'status': 'error', 'type': 'PortAudioError',
            'args': ['Error opening RawInputStream: Invalid device', -9996]}
    elif case['operation'] == 'callback':
        assert candidate == baseline == {
            'status': 'ok', 'callback': {'shape': [1024, 2], 'frames': 1024,
                                        'dtype': 'float32', 'overflow': False}}
    else:
        assert candidate == baseline
        assert candidate['status'] == (
            'error' if case['operation'] == 'invalid' else 'ok')
