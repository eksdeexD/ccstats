# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Battery fuel gauge — a custom voltage->level map that replaces the stock
# badgeware battery_level(). That stock formula is a sigmoid centred at 3.2 V
# (level = 123 - 123/(1+(v/3.2)**80)**0.165), so it reads 96-100% for nearly
# the whole discharge: in our two overnight runs it sat at 100% for hours and
# only moved in the final ~hour (docs/battery-curve-savemode-2026-06-13.log,
# docs/battery-curve-fullpower-2026-06-14.log). Useless as a gauge.
#
# Instead we map the measured voltage onto FIVE levels (four icon bars + an
# empty/critical state), calibrated to the full-power discharge curve — the run
# that reached the real ~2.88 V cutoff. Because voltage sags under load, a
# full-power calibration reads CONSERVATIVELY on lighter (save-mode) load, where
# the same charge rests at a higher voltage: it shows low rather than high,
# which is the safe direction for a low-battery warning.
#
# Two helpers above the raw reading make it stable:
#   - a median over a short window of samples kills the load-spike outliers the
#     curves show (e.g. a lone 3.28 V dip between two 3.45 V neighbours), and
#   - a small hysteresis margin stops a bar flickering at a boundary.
# The critical state LATCHES (clears only on USB) so a brief voltage recovery
# when load relaxes can't cancel a warning the cell has genuinely earned.

import badgeware  # noqa: F401 -- injects the `badge` global

# Entry voltages (volts): show N bars while the median is at/above ENTRY[N].
# 4 bars >=3.70, 3 >=3.60, 2 >=3.50, 1 >=3.42, else critical (0 / blink / empty).
ENTRY = (0.0, 3.42, 3.50, 3.60, 3.70)
FULL = 4
HYSTERESIS = 0.03  # must clear a boundary by this much to climb back up a bar

# Protective power-off: a Li-ion cell shouldn't be drained toward ~3 V. On the
# full-power curve 3.20 V sits ~7-8 min from the 2.88 V cutoff, so turning off
# here loses almost no real runtime while keeping the cell out of its damage
# zone. Acts on the median (which trails a fast collapse by ~1 min), so the
# instantaneous voltage at cutoff is a touch lower — still comfortably above 3 V.
CUTOFF_VOLTS = 3.20
CUTOFF_MIN_SAMPLES = 3  # never power off on a single cold-boot reading

# "Full enough to stop the charging sweep." The charger keeps asserting
# "charging" (CHARGE_STAT low -> badge.is_charging() True) even at a genuinely
# full cell — verified by reading the badge after a full overnight charge while
# powered off: it rested at 4.22 V yet is_charging() was still True. So the
# hardware never gives us a "charge complete" edge to act on. Instead we call
# the cell full once the smoothed voltage reaches this while on USB: 4.05 V is
# effectively 100% for a Li-ion and sits well below the ~4.2 V charged rest
# voltage, so it triggers reliably without tripping mid-charge.
FULL_ON_USB_VOLTS = 4.05

# The sweep should also only run while charge actually PROGRESSES. A healthy
# charge lifts the smoothed voltage by tens of mV per window; a charger that
# asserts CHARGE_STAT while delivering no current (observed 2026-09-02: cell
# parked dead flat at ~3.93 V for 24+ h with "charging" asserted — charger
# fault or worn pack) would otherwise sweep forever below the full gate.
RISE_VOLTS = 0.01  # smoothed gain that counts as progress
RISE_WINDOW_MS = 600000  # re-stall after this long without further progress
# PESSIMISTIC: the sweep starts hidden (boot and every power edge) and shows
# only once a rise is demonstrated — a genuine charge proves itself within a
# minute or two, and a dead charger never gets to animate at all (user call
# 2026-09-02: a sweep that is "essentially on all the time" is worse than a
# level display).

_SAMPLE_MILLISECONDS = 15000  # ADC read cadence
_WINDOW = 8  # samples kept for the median (~2 min at 15 s)

_samples = []
_last_sample_ticks = None
_cells = None  # displayed bar count 0..4, None until the first sample primes it
_critical_latched = False
_rise_ref_v = None  # smoothed voltage the rise tracker measures progress from
_rise_ref_ticks = None
_rise_stalled = True  # pessimistic until a rise is demonstrated
_last_usb = None


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _recompute():
    global _cells, _critical_latched
    if not _samples:
        return
    v = _median(_samples)
    target = 0
    for n in range(FULL, 0, -1):
        if v >= ENTRY[n]:
            target = n
            break
    if _cells is None or target < _cells:
        _cells = target  # prime, or drop immediately — discharge is the truth
    elif target > _cells and v >= ENTRY[_cells + 1] + HYSTERESIS:
        _cells += 1  # climb one bar only once we've cleared the boundary margin
    if _cells == 0:
        _critical_latched = True


def sample_if_due():
    """Call every loop pass: reads vbat on its own cadence and updates the level."""
    global _last_sample_ticks
    now = badge.ticks
    if _last_sample_ticks is not None and now - _last_sample_ticks < _SAMPLE_MILLISECONDS:
        return
    _last_sample_ticks = now
    _samples.append(badge.battery_voltage())
    if len(_samples) > _WINDOW:
        _samples.pop(0)
    _recompute()
    _track_rise(now)


def _track_rise(now):
    # progress = the smoothed voltage gaining RISE_VOLTS over the reference.
    # A dip moves the reference DOWN without clearing a stall, so a charger
    # cycling around the recharge threshold sweeps during genuine top-ups but
    # a flatlined "charging" claim stalls out after RISE_WINDOW_MS.
    global _rise_ref_v, _rise_ref_ticks, _rise_stalled
    v = _median(_samples)
    if _rise_ref_v is None or v >= _rise_ref_v + RISE_VOLTS:
        if _rise_ref_v is not None:
            _rise_stalled = False
        _rise_ref_v = v
        _rise_ref_ticks = now
    elif v < _rise_ref_v:
        _rise_ref_v = v
        _rise_ref_ticks = now
    elif now - _rise_ref_ticks >= RISE_WINDOW_MS:
        _rise_stalled = True


def prime():
    """Seed the gauge with one immediate reading before the first paint."""
    sample_if_due()


def note_power(usb_connected):
    """USB clears the critical latch (the cell is charging again); any power
    edge re-arms the rise tracker so a fresh charge gets its optimistic
    sweep while the evidence accumulates."""
    global _critical_latched, _rise_ref_v, _rise_ref_ticks, _rise_stalled, _last_usb
    if usb_connected:
        _critical_latched = False
    if usb_connected != _last_usb:
        _last_usb = usb_connected
        _rise_ref_v = None
        _rise_ref_ticks = None
        _rise_stalled = True  # every power edge re-proves itself


def cells():
    """Displayed bar count 0..4 (4 until the first sample primes it)."""
    return FULL if _cells is None else _cells


def critical():
    """True once the cell has reached the lowest level (latched until USB)."""
    return _critical_latched


def voltage():
    """The smoothed (median) voltage, or None before priming."""
    return _median(_samples) if _samples else None


def charged_full():
    """True when the smoothed voltage says the cell is effectively full. The
    caller only consults this while charging (so USB is already guaranteed); it
    lets us show a static full icon instead of the endless charging sweep, since
    the charger never reports 'done' to us. False before priming."""
    v = voltage()
    return v is not None and v >= FULL_ON_USB_VOLTS


def charge_progressing():
    """True only while a claimed charge has demonstrated real progress —
    the smoothed voltage gaining RISE_VOLTS — within the last
    RISE_WINDOW_MS. Starts False (boot and every power edge): a genuine
    charge proves itself within a minute or two of samples, while a
    charger asserting CHARGE_STAT with no real current (this hardware,
    observed 2026-09-02) never animates the sweep at all. A real charge
    hits charged_full() long before its taper flattens below the
    threshold."""
    return not _rise_stalled


def should_power_off(on_battery):
    """True when, on battery, the smoothed voltage has reached the protective
    cutoff. Gated on a primed window so a single bad cold-boot read can't
    trigger it, and never fires on USB (the caller passes on_battery)."""
    return (on_battery
            and len(_samples) >= CUTOFF_MIN_SAMPLES
            and _median(_samples) <= CUTOFF_VOLTS)
