"""Measurements as bare functions, so a calc cell shows them as equations.

A calc cell renders bare function calls but not method calls, so each
measurement of a simulated signal, a waveform, a network or a timing report is
also a function::

    # %% calc response "Simulated response"
    f_sim = cutoff(H)                 # -> kHz
    t_r = rise_time(v_out)            # -> us
    PM = phase_margin(T_loop)
    assert PM >= 45 * deg, "Phase margin"

Each is the method of the same name on the object (``cutoff(H)`` is
``H.cutoff()``); see :class:`kip.spice.Signal` for what they measure.
"""
from __future__ import annotations

from .spice import HALF_POWER

__all__ = ["cutoff", "bandwidth", "gain_at", "crossover", "phase_margin", "gain_margin", "resonance",
           "rise_time", "fall_time", "overshoot", "settling_time", "period", "rms", "average", "peak",
           "peak_to_peak", "value_at", "pulse_width", "fmax"]


def cutoff(signal, level: float = HALF_POWER):
    """Where a response falls 3 dB (half power) from its passband."""
    return signal.cutoff(level)


def bandwidth(response, level: float | None = None, port: int = 1):
    """A response's -3 dB bandwidth, or a network's impedance bandwidth (|Sii| < -10 dB)."""
    from .rf import Network
    if isinstance(response, Network):
        return response.bandwidth(port, -10.0 if level is None else level)
    return response.bandwidth(HALF_POWER if level is None else level)


def gain_at(response, f) -> float:
    """The gain in dB at frequency ``f``."""
    return response.gain_at(f)


def crossover(loop):
    """Where a loop gain falls through 0 dB."""
    return loop.unity_gain_frequency()


def phase_margin(loop):
    return loop.phase_margin()


def gain_margin(loop) -> float:
    return loop.gain_margin()


def resonance(network, port: int = 1):
    """A network's best match: the frequency of the least |Sii|."""
    return network.resonance(port)


def rise_time(signal, low: float = 0.1, high: float = 0.9):
    return signal.rise_time(low, high)


def fall_time(signal, high: float = 0.9, low: float = 0.1):
    return signal.fall_time(high, low)


def overshoot(signal):
    return signal.overshoot()


def settling_time(signal, tolerance: float = 0.02):
    return signal.settling_time(tolerance)


def period(signal):
    """A periodic signal's period: analogue (mean rising crossings) or a digital wave."""
    return signal.period()


def rms(signal):
    return signal.rms()


def average(signal):
    return signal.mean()


def peak(signal):
    return signal.peak()


def peak_to_peak(signal):
    return signal.peak_to_peak()


def value_at(signal, x):
    """A signal's value at sweep point ``x`` (a time or a frequency)."""
    return signal.at(x)


def pulse_width(wave, level: int = 1, n: int = 1):
    """How long a digital wave's ``n``-th complete pulse at ``level`` (0 or 1) lasts."""
    return wave.pulse(str(int(level)), n)


def fmax(report, clock: str | None = None):
    """A timing report's achieved maximum clock frequency (the slowest clock's)."""
    return report.fmax(clock)
