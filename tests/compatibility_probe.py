"""Run identical public API calls in an isolated interpreter for each revision."""

import itertools
import json


class CompatibilityProbe:
    """Synthetic ALSA public-API comparison, excluding physical audio behavior."""

    @staticmethod
    def cases():
        cases = []
        for kind, selector, latency, defaults in itertools.product(
                ('input', 'output', 'duplex'), ('index', 'name', 'default'),
                ('low', 'high', 0.05), (False, True)):
            cases.append(dict(operation='stream', kind=kind, selector=selector,
                              latency=latency, defaults=defaults))
        for kind, selector, defaults in itertools.product(
                ('input', 'output'), ('index', 'name', 'default'), (False, True)):
            cases.append(dict(operation='check', kind=kind, selector=selector,
                              latency='high', defaults=defaults))
        for selector in ('index', 'name', 'default'):
            cases.append(dict(operation='callback', kind='input',
                              selector=selector, latency='high', defaults=False))
        for invalid in ('device', 'channels', 'dtype', 'samplerate'):
            cases.append(dict(operation='invalid', kind='input', selector='index',
                              latency=0.05, defaults=False, invalid=invalid))
        cases.append(dict(operation='check_ignored_latency', kind='input',
                          selector='index', latency='invalid', defaults=False))
        return cases

    @staticmethod
    def execute(sd, case, index):
        sd.default.reset()
        sd.default.device = index
        sd.default.latency = case['latency']
        device = dict(index=index, name='test_named', default=None)[case['selector']]
        options = dict(device=device, channels=2, samplerate=48000, dtype='int16')
        if case['defaults']:
            sd.default.channels = 2
            sd.default.samplerate = 48000
            del options['channels']
            del options['samplerate']
        operation = case['operation']
        if operation in ('check', 'check_ignored_latency'):
            getattr(sd, 'check_' + case['kind'] + '_settings')(**options)
            return dict(status='ok')
        if operation == 'callback':
            import threading
            finished = threading.Event()
            received = {}

            def callback(data, frames, time, status):
                received.update(shape=list(data.shape), frames=frames,
                                dtype=str(data.dtype), overflow=status.input_overflow)
                raise sd.CallbackStop

            options['dtype'] = 'float32'
            with sd.InputStream(
                    **options, blocksize=1024,
                    callback=callback, finished_callback=finished.set):
                if not finished.wait(5):
                    raise TimeoutError('Input callback did not finish')
            return dict(status='ok', callback=received)
        options.update(blocksize=1024, latency=case['latency'])
        if operation == 'invalid':
            key = case['invalid']
            options[key] = dict(device=9999, channels=0, dtype='invalid',
                                samplerate=-1)[key]
        cls = dict(input=sd.RawInputStream, output=sd.RawOutputStream,
                   duplex=sd.RawStream)[case['kind']]
        with cls(**options) as stream:
            result = dict(status='ok', device=stream.device,
                          channels=stream.channels, samplerate=stream.samplerate,
                          dtype=stream.dtype)
            if case['kind'] in ('output', 'duplex'):
                result['underflow'] = stream.write(bytes(4096))
            if case['kind'] in ('input', 'duplex'):
                data, overflow = stream.read(1024)
                result.update(bytes=len(data), overflow=overflow)
            return result

    @classmethod
    def run(cls):
        import sounddevice as sd
        index = next(i for i, d in enumerate(sd.query_devices())
                     if d['name'] == 'test_named')
        results = []
        for case in cls.cases():
            try:
                result = cls.execute(sd, case, index)
            except Exception as error:
                result = dict(status='error', type=type(error).__name__,
                              args=list(error.args))
            results.append(result)
        return dict(module=sd.__file__, results=results)


if __name__ == '__main__':
    print(json.dumps(CompatibilityProbe.run()))
