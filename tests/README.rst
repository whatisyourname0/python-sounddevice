Synthetic ALSA tests
===================

These Linux tests exercise sounddevice and the real PortAudio ALSA backend
using null and file PCMs. No microphone or sound card is needed.
Run them in a fresh Python process so the isolated ALSA configuration is set
before PortAudio initialization. The fixture does not include system or user
ALSA configuration and restores the environment when the test session ends.

Install PortAudio and ALSA plugins (Debian/Ubuntu)::

    sudo apt-get install libportaudio2
    python -m pip install . pytest numpy
    python -m pytest -q tests

The temporary directory contains a deterministic input file and ALSA config.
It is removed at the end of the session. Non-Linux runs skip these tests;
missing ALSA support on Linux fails rather than silently skipping coverage.

The tests cover direct input/output/duplex, exact input bytes, close/reopen,
invalid parameters, settings lifetime, explicit sentinel defaults and indexed
and named selection. They do not validate hardware identity, physical capture,
hotplug, real-time scheduling or a negotiated hardware buffer size.

The raw-stream tests require only pytest and sounddevice. The convenience API
test uses NumPy and reports a skip when NumPy is unavailable.
This branch contains the tests separately from the feature PR; it does not
add pytest dependencies or test steps to the upstream CI configuration.

ALSA_CONFIG_PATH cannot represent spaces or colons in its configuration path.
If the process temporary directory contains either, the fixture uses /tmp.

Explicit device selection
-------------------------

Direct PCM streams use ``device=sd.DEVICE_FROM_EXTRA_SETTINGS`` with
``extra_settings=sd.AlsaSettings('null')``. The sentinel can also be set in
``sd.default.device``. Supplying ``AlsaSettings`` alone never changes the
selected device; PortAudio rejects it with a regular ALSA device index.

The tests also cover lazy device-info queries without ALSA settings, symbolic
latency and missing-default failures, error propagation and recovery, format
checks without latency, mixed direct/indexed duplex, and retained C buffers.
All streams use synthetic PCMs. Physical devices and hotplug are not covered.

Baseline compatibility comparison
--------------------------------

``test_compatibility.py`` runs 74 identical public API calls in separate Python
processes for the PR base (``626fcb071638ebbb631ccd40f3307f8dce68af63``) and the
installed candidate. Both processes inherit the same isolated ALSA fixture.
The baseline source must be built before running this optional comparison::

    python -m pip install . pytest numpy
    baseline_dir=$(mktemp -d /tmp/sounddevice-baseline.XXXXXX)
    git archive 626fcb071638ebbb631ccd40f3307f8dce68af63 | tar -x -C "$baseline_dir"
    (cd "$baseline_dir" && python sounddevice_build.py)
    SOUNDDEVICE_BASELINE_PATH="$baseline_dir/src" python -m pytest -q tests

Without ``SOUNDDEVICE_BASELINE_PATH``, pytest explicitly skips the differential
cases; the direct-ALSA suite still runs. The baseline directory is retained for
inspection until manually removed. A failing subprocess or a timeout fails the
comparison instead of being treated as a matching error.

The comparison covers input/output/duplex streams, index/name/default selection,
numeric and low/high latency, configured channel/rate defaults, format checks,
invalid arguments, and float32 InputStream callbacks with implicit latency.
Successful results include device, channel count, rate, dtype and I/O completion.
Callbacks must deliver a 1024-by-2 float32 block and finish normally.

At feature revision ``ffcda44``, 72 calls match exactly. Two intentional changes
are asserted separately with exact outcomes:

* An invalid numeric device with fully explicit parameters now fails in stream
  opening with PortAudio's invalid-device code, instead of in query_devices().
* Format checks ignore invalid default latency, since PortAudio does not use
  latency for format checking; the baseline raised TypeError.

This comparison does not establish Windows/ASIO/WASAPI or macOS/CoreAudio
compatibility, nor physical hardware behavior. Both revisions use ALSA
null/file PCMs.

Device-information errors
-------------------------

A failed parameter lookup reports the first unresolved value in a TypeError,
chaining the original PortAudioError as its cause. The suite checks input and
output, individual and combined missing values, format checks without latency,
recovery, and propagation of unrelated exceptions without wrapping.
The 74-call baseline comparison retains the same two documented differences.

Native validation boundaries
----------------------------

Numeric values use the same conversion path for indexed and direct devices.
Non-positive direct channel counts remain rejected before calling PortAudio:
PortAudio 19.6.0's ALSA direct-device path aborts on channels=0. These regression
checks run in child processes so a native abort cannot terminate the test suite.
Embedded NUL characters remain rejected because a C string would silently
truncate the PCM address. Empty addresses are passed to ALSA.
