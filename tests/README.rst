Synthetic ALSA tests
===================

These Linux tests exercise sounddevice and the real PortAudio ALSA backend
using plug, null and file PCMs. No microphone or sound card is needed.
Run in a fresh Python process so the fixture configures ALSA before PortAudio
initializes. It excludes system/user ALSA configuration and removes its
temporary configuration and deterministic audio files when the session ends.

Install PortAudio and the test dependencies (Debian/Ubuntu)::

    sudo apt-get install libportaudio2
    python -m pip install . pytest numpy
    python -m pytest -q tests

Non-Linux runs skip the ALSA tests. Missing ALSA support on Linux fails.
Install NumPy for the callback and convenience-API comparisons.
This branch keeps tests separate from the feature PR and adds no upstream
test dependencies or CI steps.

Baseline compatibility comparison
---------------------------------

``test_compatibility.py`` runs 125 identical public API calls in separate
interpreters for PR base ``626fcb071638ebbb631ccd40f3307f8dce68af63`` and the
installed candidate. Both inherit the same isolated ALSA configuration.
Build the baseline and enable the comparison as follows::

    python -m pip install . pytest numpy
    baseline_dir=$(mktemp -d /tmp/sounddevice-baseline.XXXXXX)
    git archive 626fcb071638ebbb631ccd40f3307f8dce68af63 | tar -x -C "$baseline_dir"
    (cd "$baseline_dir" && python sounddevice_build.py)
    SOUNDDEVICE_BASELINE_PATH="$baseline_dir/src" python -m pytest -q tests

Without ``SOUNDDEVICE_BASELINE_PATH``, those 125 cases are explicitly skipped;
the other 79 cases still run. The baseline directory remains for inspection
until manually removed. Subprocess failures and timeouts fail the comparison.

Coverage includes index/name/default selection, raw input/output/duplex,
numeric and low/high latency, configured and device-derived channel/rate
defaults, format checks, invalid arguments, float32 input/output/duplex
callbacks, and play()/rec()/playrec(). Successful results include device,
channel count, sample rate, dtype and I/O completion. Callback cases must
deliver a 1024-by-2 float32 block and finish normally.

114 outcomes match exactly. Eleven cases assert three intentional differences:

* An invalid numeric device with fully specified parameters fails during
  stream opening with PortAudio's invalid-device code, instead of querying.
* Format checks ignore invalid default latency, since PortAudio does not use
  latency for format checking; the baseline raised TypeError.
* Nine cases with an invalid device and missing channels and/or sample rate
  raise TypeError naming the first unresolved parameter. The baseline's
  PortAudioError is preserved as the cause, not the top-level exception.
  Applications catching only PortAudioError must account for this difference.

Direct-device and error coverage
-------------------------------

Direct PCMs use ``device=sd.DEVICE_FROM_EXTRA_SETTINGS`` and
``extra_settings=sd.AlsaSettings('null')``. The sentinel may also be assigned
to ``sd.default.device``. Settings alone never change device selection;
PortAudio rejects them with a regular ALSA device index.

Tests cover input/output/duplex, byte-exact file input, close/reopen, mixed
direct/indexed duplex, defaults, missing values, symbolic latency, format
checks without latency, recovery, exception chaining and propagation of
unrelated exceptions. Shared handling is also tested without AlsaSettings
class identity.

Non-positive direct channel counts are rejected before PortAudio can abort
the process in a C assertion. Those cases run in child processes. Embedded
NUL characters are rejected to prevent silent C-string truncation; empty
addresses are passed to ALSA. Other numeric values follow the same conversion
path as indexed devices.

Settings lifetime
-----------------

PortAudio 19.6.0 and upstream commit
``1ca0eeedb678c3cca80f3306c474d69a7a4b5278`` access ``deviceString`` during
validation, PCM opening and stream initialization. Neither the ALSA stream
nor its component retains that pointer. Settings must survive the native
open/format-check call, but need not survive until stream close.

Tests observe settings throughout real native open/format-check calls, then
verify collection before start, allocate replacement buffers, run
start/stop/start and compare captured bytes. Callback I/O is also tested
after collection, for input/output/duplex with real PortAudio.

No matching PortAudio issue was found in the 2026-10-25 search for
channelCount/assert, zero channels, numUserChannels, deviceString and
paUseHostApiSpecificDeviceSpecification. Issues 278 and 295 concern other
capture failures, not this validation gap. The workaround links to the
reviewer's reproduction in PR 644.

Validation and limits
---------------------

On 2026-10-25, all 204 tests passed on Linux ARM64 and CPython 3.14.7,
separately with installed PortAudio 19.6.0 and PortAudio built with ALSA from
``1ca0eeedb678c3cca80f3306c474d69a7a4b5278``. The latter reports 19.7.0-devel;
the commit identifies the tested source. Both runs include all 125 baseline
comparisons, with no skips.

The named/default fixture uses plug with a stereo null slave. Raw null's
enormous maximum channel count is rejected during enumeration by newer
PortAudio. A multi-over-null fixture passed blocking I/O but stalled output
callbacks on the baseline too; plug completes both and exposes a bounded
channel range. Direct and file-capture tests retain the null/file PCMs.
ALSA_CONFIG_PATH cannot represent spaces or colons, so the fixture falls
back to /tmp when the process temporary-directory path contains either.

These tests do not establish physical capture/playback, hardware identity,
hotplug, real-time scheduling, negotiated hardware buffer sizes, or native
Windows/macOS compatibility.
