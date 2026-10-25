"""Verify ALSA settings ownership at the native call and callback boundaries."""

import gc
import sys
import threading
import weakref

import pytest

if sys.platform != 'linux':
    pytest.skip('ALSA integration requires Linux', allow_module_level=True)

import sounddevice as sd


@pytest.fixture(autouse=True)
def reset_defaults():
    """Isolate each case's module-wide settings."""
    sd.default.reset()
    yield
    sd.default.reset()


@pytest.mark.parametrize('operation', [
    'input', 'output', 'duplex', 'check_input', 'check_output',
])
@pytest.mark.parametrize('use_defaults', [False, True])
def test_settings_survive_native_call_only(operation, use_defaults, monkeypatch):
    """Temporary settings survive the real native call, without stream ownership."""
    refs = []
    calls = []
    native = sd._lib

    def make_settings():
        settings = sd.AlsaSettings('null')
        refs.append(weakref.ref(settings))
        return settings

    class ObserveNativeCalls:
        def __getattr__(self, name):
            return getattr(native, name)

        def Pa_OpenStream(self, *args):
            gc.collect()
            assert all(ref() is not None for ref in refs)
            result = native.Pa_OpenStream(*args)
            assert all(ref() is not None for ref in refs)
            calls.append('open')
            return result

        def Pa_IsFormatSupported(self, *args):
            gc.collect()
            assert all(ref() is not None for ref in refs)
            result = native.Pa_IsFormatSupported(*args)
            assert all(ref() is not None for ref in refs)
            calls.append('check')
            return result

    monkeypatch.setattr(sd, '_lib', ObserveNativeCalls())
    if use_defaults:
        sd.default.extra_settings = make_settings(), make_settings()
    options = dict(device=sd.DEVICE_FROM_EXTRA_SETTINGS, channels=2,
                   samplerate=48000, dtype='int16')
    stream = None
    try:
        if operation.startswith('check_'):
            check = getattr(sd, operation + '_settings')
            check(**options, extra_settings=(
                None if use_defaults else (make_settings(), make_settings())))
            assert calls == ['check']
        else:
            cls = {'input': sd.RawInputStream, 'output': sd.RawOutputStream,
                   'duplex': sd.RawStream}[operation]
            stream = cls(**options, latency=0.05, extra_settings=(
                None if use_defaults else (make_settings(), make_settings())))
            assert calls == ['open']
        sd.default.reset()
        gc.collect()
        assert len(refs) == 2
        assert all(ref() is None for ref in refs)
    finally:
        if stream is not None:
            stream.close()


@pytest.mark.parametrize('direction', ['input', 'output', 'duplex'])
def test_callback_after_settings_collection(direction, alsa_capture_bytes):
    """Native callbacks still exchange complete buffers after settings collection."""
    finished = threading.Event()
    received = []

    def callback(*args):
        if direction == 'duplex':
            indata, outdata, frames, _, status = args
        elif direction == 'input':
            indata, frames, _, status = args
            outdata = None
        else:
            outdata, frames, _, status = args
            indata = None
        if outdata is not None:
            outdata[:] = bytes(len(outdata))
        received.append((frames, bytes(indata) if indata is not None else None,
                         len(outdata) if outdata is not None else None,
                         status.input_overflow))
        raise sd.CallbackStop

    input_settings = sd.AlsaSettings('portaudio_file_capture')
    output_settings = sd.AlsaSettings('null')
    refs = [weakref.ref(input_settings), weakref.ref(output_settings)]
    cls = {'input': sd.RawInputStream, 'output': sd.RawOutputStream,
           'duplex': sd.RawStream}[direction]
    stream = cls(device=sd.DEVICE_FROM_EXTRA_SETTINGS, channels=2,
                 samplerate=48000, dtype='int16', blocksize=1024, latency=0.05,
                 extra_settings=(input_settings, output_settings),
                 callback=callback, finished_callback=finished.set)
    try:
        del input_settings, output_settings
        gc.collect()
        assert all(ref() is None for ref in refs)
        replacements = [sd.AlsaSettings('no_such_pcm_after_open')
                        for _ in range(1000)]
        stream.start()
        assert finished.wait(5), 'The native callback did not finish'
        assert len(received) == 1
        frames, data, output_size, overflow = received[0]
        assert frames == 1024
        assert not overflow
        if direction != 'output':
            assert data == alsa_capture_bytes[:4096]
        if direction != 'input':
            assert output_size == 4096
        assert len(replacements) == 1000
    finally:
        stream.close()
