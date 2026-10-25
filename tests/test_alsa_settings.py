"""Synthetic Linux integration. No physical microphone acceptance."""

import gc
import sys
import weakref

import pytest

if sys.platform != 'linux':
    pytest.skip('ALSA integration requires Linux', allow_module_level=True)

import sounddevice as sd


@pytest.fixture(autouse=True)
def reset_defaults():
    sd.default.reset()
    yield
    sd.default.reset()


def params(**kwargs):
    options = dict(
        device=sd.DEVICE_FROM_EXTRA_SETTINGS,
        samplerate=48000,
        channels=2,
        dtype='int16',
        blocksize=1024,
        latency=4096 / 48000,
        extra_settings=sd.AlsaSettings('null'),
    )
    options.update(kwargs)
    return options


def forbid_query(*args, **kwargs):
    raise AssertionError('Device name enumeration was used')


def test_file_pcm_bytes_and_reopen(monkeypatch, alsa_capture_bytes):
    """File pcm bytes and reopen."""
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    expected = alsa_capture_bytes[:16384]
    for _ in range(2):
        options = params()
        options['extra_settings'] = sd.AlsaSettings('portaudio_file_capture')
        with sd.RawInputStream(**options) as stream:
            actual = b''.join(bytes(stream.read(1024)[0]) for _ in range(4))
            assert stream.device == -2
            assert actual == expected


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_format_check_needs_no_latency_or_enumeration(monkeypatch, direction):
    """Format check needs no latency or enumeration."""
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    getattr(sd, 'check_' + direction + '_settings')(
        device=sd.DEVICE_FROM_EXTRA_SETTINGS,
        channels=2,
        samplerate=48000,
        dtype='int16',
        extra_settings=sd.AlsaSettings('null'),
    )


@pytest.mark.parametrize('selector', ['index', 'name', 'default'])
def test_settings_alone_do_not_override_device(selector):
    """An ALSA address only takes effect with explicit sentinel selection."""
    index = next(i for i, d in enumerate(sd.query_devices())
                 if d['name'] == 'test_named')
    sd.default.device = index
    options = params(device={'index': index, 'name': 'test_named',
                             'default': None}[selector])
    with pytest.raises(sd.PortAudioError) as caught:
        sd.RawInputStream(**options)
    assert caught.value.args[1] == -9993  # paBadIODeviceCombination
    options['extra_settings'] = None
    with sd.RawInputStream(**options) as stream:
        assert stream.device == index
        assert len(stream.read(1024)[0]) == 4096
    with sd.RawInputStream(**params()) as stream:
        assert stream.device == -2


@pytest.mark.parametrize('value', ['null\x00bad'])
def test_bad_address(value):
    """Bad address."""
    with pytest.raises((TypeError, ValueError)):
        sd.AlsaSettings(value)


@pytest.mark.parametrize(
    'key,value',
    [
        ('channels', None),
        ('samplerate', None),
        ('latency', 'high'),
    ],
)
def test_missing_or_invalid_explicit_parameters(key, value):
    """Missing or invalid explicit parameters."""
    options = params()
    options[key] = value
    with pytest.raises((TypeError, ValueError, sd.PortAudioError)):
        sd.RawInputStream(**options)


def test_missing_pcm_does_not_fallback():
    """Missing pcm does not fallback."""
    options = params()
    options['extra_settings'] = sd.AlsaSettings('no_such_pcm_abc')
    with pytest.raises(sd.PortAudioError):
        sd.RawInputStream(**options)
    with sd.RawInputStream(**params()) as stream:
        assert len(stream.read(1024)[0]) == 4096


def test_defaults_and_settings_lifetime(monkeypatch):
    """Defaults and settings lifetime."""
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    sd.default.device = 9876
    sd.default.channels = 2
    sd.default.samplerate = 48000
    sd.default.latency = 4096 / 48000
    settings = sd.AlsaSettings('null')
    ref = weakref.ref(settings)
    sd.default.extra_settings = settings
    stream = sd.RawInputStream(device=sd.DEVICE_FROM_EXTRA_SETTINGS,
                               dtype='int16', blocksize=1024)
    sd.default.reset()
    del settings
    gc.collect()
    assert ref() is not None
    with stream:
        assert len(stream.read(1024)[0]) == 4096
    del stream
    gc.collect()
    assert ref() is None


def test_output_and_duplex(monkeypatch):
    """Output and duplex."""
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    with sd.RawOutputStream(**params()) as stream:
        stream.write(bytes(4096))
    options = params()
    options['extra_settings'] = (sd.AlsaSettings('null'), sd.AlsaSettings('null'))
    with sd.RawStream(**options) as stream:
        assert stream.device == (-2, -2)
        stream.write(bytes(4096))
        assert len(stream.read(1024)[0]) == 4096


def test_explicit_sentinel(monkeypatch):
    """Explicit sentinel."""
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    with sd.RawInputStream(**params(device=-2)) as stream:
        assert len(stream.read(1024)[0]) == 4096


def test_legacy_index_and_name():
    """Legacy index and name."""
    devices = sd.query_devices()
    index = next(i for i, d in enumerate(devices) if d['name'] == 'test_named')
    for selector in [index, 'test_named']:
        options = params()
        del options['extra_settings']
        options['device'] = selector
        with sd.RawInputStream(**options) as stream:
            assert stream.device == index
            assert len(stream.read(1024)[0]) == 4096


def test_convenience_mapping_is_explicit_error(monkeypatch):
    """Convenience mapping is explicit error."""
    np = pytest.importorskip('numpy', reason='Convenience API requires NumPy')
    with pytest.raises(sd.PortAudioError, match='Error querying device'):
        sd.play(
            np.zeros(128, dtype='float32'),
            48000,
            mapping=[1],
            device=sd.DEVICE_FROM_EXTRA_SETTINGS,
            extra_settings=sd.AlsaSettings('null'),
            latency=0.05,
        )


@pytest.mark.parametrize(
    'kind,device',
    [
        ('input', (-2, 7)),
        ('output', (7, -2)),
    ],
)
def test_one_direction_device_pair(kind, device):
    """One direction device pair."""
    cls = sd.RawInputStream if kind == 'input' else sd.RawOutputStream
    with cls(**params(device=device)) as stream:
        assert stream.device == -2


@pytest.mark.parametrize('key,value', [
    ('channels', True), ('samplerate', True),
    ('samplerate', float('nan')), ('latency', True),
    ('latency', float('inf')), ('latency', -1),
])
def test_numeric_parameters_have_no_device_specific_validation(key, value):
    """Indexed and direct paths pass the same numeric values to PortAudio."""
    import math

    results = []
    for device, settings in [(0, None),
                             (sd.DEVICE_FROM_EXTRA_SETTINGS, sd.AlsaSettings('null'))]:
        options = dict(channels=2, dtype='int16', latency=0.05, samplerate=48000)
        options[key] = value
        parameters, _, _, samplerate, owner = sd._get_stream_parameters(
            'input', device=device, extra_settings=settings, **options)
        actual = dict(channels=parameters.channelCount,
                      samplerate=samplerate, latency=parameters.suggestedLatency)[key]
        results.append(actual)
        assert owner is settings
    if isinstance(value, float) and math.isnan(value):
        assert all(math.isnan(result) for result in results)
    else:
        assert results[0] == results[1] == value


def test_mixed_direct_and_indexed_duplex():
    """Mixed direct and indexed duplex."""
    index = next(
        i for i, d in enumerate(sd.query_devices()) if d['name'] == 'test_named'
    )
    options = params()
    options['device'] = (sd.DEVICE_FROM_EXTRA_SETTINGS, index)
    options['extra_settings'] = (sd.AlsaSettings('null'), None)
    with sd.RawStream(**options) as stream:
        assert stream.device == (-2, index)
        stream.write(bytes(4096))
        assert len(stream.read(1024)[0]) == 4096


def test_missing_alsa_backend_error(monkeypatch):
    """An unavailable native initializer raises the normal symbol error."""
    monkeypatch.setattr(sd, '_lib', object())
    with pytest.raises(AttributeError, match='PaAlsa_InitializeStreamInfo'):
        sd.AlsaSettings('null')


def test_explicit_none_settings_pair_does_not_reapply_defaults():
    """Explicit none settings pair does not reapply defaults."""
    sd.default.extra_settings = sd.AlsaSettings('no_such_pcm_abc')
    sd.check_input_settings(device='test_named', channels=2, samplerate=48000,
                            dtype='int16', extra_settings=(None, None))


def test_mutable_settings_container_lifetime():
    """Mutable settings container lifetime."""
    settings = sd.AlsaSettings('null')
    ref = weakref.ref(settings)
    pair = [settings, None]
    options = params()
    options['extra_settings'] = pair
    stream = sd.RawInputStream(**options)
    pair.clear()
    del settings
    gc.collect()
    try:
        assert ref() is not None
        with stream:
            assert len(stream.read(1024)[0]) == 4096
    finally:
        stream.close()


@pytest.mark.parametrize('direction', ['input', 'output'])
@pytest.mark.parametrize('key,value', [
    ('channels', None), ('samplerate', None),
    ('latency', 'low'), ('latency', 'high'),
])
def test_device_information_failures_propagate(direction, key, value, monkeypatch):
    """Missing defaults propagate query failures even without ALSA settings."""
    index = next(i for i, d in enumerate(sd.query_devices())
                 if d['name'] == 'test_named')
    failure = sd.PortAudioError('Device information unavailable')

    def unavailable(*args, **kwargs):
        raise failure

    options = params(device=index, extra_settings=None)
    options[key] = value
    cls = sd.RawInputStream if direction == 'input' else sd.RawOutputStream
    with monkeypatch.context() as patch:
        patch.setattr(sd, 'query_devices', unavailable)
        with pytest.raises(TypeError) as caught:
            cls(**options)
        required = 'numeric latency' if key == 'latency' else key
        assert str(caught.value) == (
            'Cannot determine {} from device information; '
            'specify {} explicitly or through defaults'.format(key, required))
        assert caught.value.__cause__ is failure
    with cls(**params(device=index, extra_settings=None)) as stream:
        assert stream.device == index


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_explicit_index_parameters_need_no_device_query(direction, monkeypatch):
    """Fully specified indexed streams do not depend on device information."""
    index = next(i for i, d in enumerate(sd.query_devices())
                 if d['name'] == 'test_named')
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    cls = sd.RawInputStream if direction == 'input' else sd.RawOutputStream
    with cls(**params(device=index, extra_settings=None)) as stream:
        assert stream.device == index


@pytest.mark.parametrize('latency', ['low', 'high'])
def test_indexed_streams_still_resolve_defaults(latency):
    """Indexed streams continue to derive sample rate, channels and latency."""
    with sd.RawInputStream(device='test_named', latency=latency) as stream:
        assert stream.channels > 0
        assert stream.samplerate > 0


def test_sentinel_can_be_selected_in_defaults(monkeypatch):
    """Default sentinel and settings retain direct-address selection."""
    sd.default.device = sd.DEVICE_FROM_EXTRA_SETTINGS
    sd.default.extra_settings = sd.AlsaSettings('null')
    options = params()
    del options['device']
    del options['extra_settings']
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    with sd.RawInputStream(**options) as stream:
        assert stream.device == -2
        assert len(stream.read(1024)[0]) == 4096


def test_sentinel_requires_settings_and_recovers():
    """Missing settings fail before opening, and a corrected call succeeds."""
    with pytest.raises(sd.PortAudioError, match='Invalid device'):
        sd.RawInputStream(**params(extra_settings=None))
    with sd.RawInputStream(**params()) as stream:
        assert len(stream.read(1024)[0]) == 4096


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_indexed_format_checks_ignore_default_latency(direction, monkeypatch):
    """Format checks do not query device information solely for latency."""
    index = next(i for i, d in enumerate(sd.query_devices())
                 if d['name'] == 'test_named')
    sd.default.latency = 'high'
    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    getattr(sd, 'check_' + direction + '_settings')(
        device=index, channels=2, samplerate=48000, dtype='int16')


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_direct_stream_accepts_settings_protocol(direction, monkeypatch):
    """Shared stream construction accepts settings without an ALSA type check."""
    class Settings:
        def __init__(self):
            self.owner = sd.AlsaSettings('null')
            self._streaminfo = self.owner._streaminfo

    monkeypatch.setattr(sd, 'query_devices', forbid_query)
    cls = sd.RawInputStream if direction == 'input' else sd.RawOutputStream
    with cls(**params(extra_settings=Settings())) as stream:
        assert stream.device == -2


@pytest.mark.parametrize('direction', ['input', 'output'])
@pytest.mark.parametrize('latency', ['low', 'high'])
def test_direct_symbolic_latency_fails_and_numeric_recovers(direction, latency):
    """Direct streams cannot derive symbolic latency from unavailable devices."""
    cls = sd.RawInputStream if direction == 'input' else sd.RawOutputStream
    with pytest.raises(TypeError, match='specify numeric latency') as caught:
        cls(**params(latency=latency))
    assert isinstance(caught.value.__cause__, sd.PortAudioError)
    assert str(caught.value.__cause__) == 'Error querying device -2'
    with cls(**params()) as stream:
        assert stream.device == -2


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_missing_parameters_report_first_requirement(direction):
    """Report the first unresolved value and retain the underlying device error."""
    cls = sd.RawInputStream if direction == 'input' else sd.RawOutputStream
    with pytest.raises(TypeError) as caught:
        cls(device=sd.DEVICE_FROM_EXTRA_SETTINGS,
            extra_settings=sd.AlsaSettings('null'))
    assert str(caught.value) == (
        'Cannot determine channels from device information; '
        'specify channels explicitly or through defaults')
    assert isinstance(caught.value.__cause__, sd.PortAudioError)


@pytest.mark.parametrize('direction', ['input', 'output'])
def test_format_check_error_does_not_request_latency(direction):
    """Format checks request missing channel/rate values but never latency."""
    with pytest.raises(TypeError) as caught:
        getattr(sd, 'check_' + direction + '_settings')(
            device=sd.DEVICE_FROM_EXTRA_SETTINGS,
            extra_settings=sd.AlsaSettings('null'))
    assert str(caught.value) == (
        'Cannot determine channels from device information; '
        'specify channels explicitly or through defaults')
    assert isinstance(caught.value.__cause__, sd.PortAudioError)


def test_unexpected_query_error_is_not_wrapped(monkeypatch):
    """Do not disguise programming errors as missing stream parameters."""
    failure = RuntimeError('unexpected query failure')

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(sd, 'query_devices', fail)
    with pytest.raises(RuntimeError) as caught:
        sd.RawInputStream(**params(latency='high'))
    assert caught.value is failure


@pytest.mark.parametrize('channels', [0, -1])
def test_nonpositive_direct_channels_do_not_abort_process(channels):
    """Invalid channel counts raise Python errors instead of native assertions."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, '-c', """
import sounddevice as sd
import sys
try:
    sd.RawInputStream(device=sd.DEVICE_FROM_EXTRA_SETTINGS,
                      extra_settings=sd.AlsaSettings('null'),
                      channels=int(sys.argv[1]), samplerate=48000,
                      dtype='int16', latency=0.05)
except ValueError as error:
    assert str(error) == 'A positive channel count is required'
else:
    raise AssertionError('invalid channel count was accepted')
""", str(channels)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_embedded_nul_would_truncate_the_native_address():
    """Reject a PCM address that C would silently interpret as another name."""
    address = 'null\0different-device'
    native = sd._ffi.new('char[]', address.encode())
    assert sd._ffi.string(native) == b'null'
    with pytest.raises(ValueError, match='NUL'):
        sd.AlsaSettings(address)


def test_empty_address_is_forwarded_to_alsa():
    """The backend owns empty-address semantics."""
    settings = sd.AlsaSettings('')
    assert sd._ffi.string(settings._streaminfo.deviceString) == b''
