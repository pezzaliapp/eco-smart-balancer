"""
Unit tests for balance_core.

Run with: pytest test/ -v
"""
import numpy as np
import pytest

from balance_core import (
    CalibrationData,
    MachineGeometry,
    SensorConfig,
    WheelGeometry,
    angular_error_deg,
    bandpass_filter,
    extract_first_harmonic,
    generate_signal,
    identify_K,
    imbalance_force_amplitude,
    run_pipeline,
    solve_imbalance,
    transfer_K_default,
)


# ---------------------------------------------------------------------
# Force calculation
# ---------------------------------------------------------------------

def test_imbalance_force_zero():
    assert imbalance_force_amplitude(0.0, 0.20, 25.0) == 0.0


def test_imbalance_force_known_values():
    # 100 g at 0.20 m at 240 rpm = 25.13 rad/s
    f = imbalance_force_amplitude(100.0, 0.20, 25.13)
    expected = 0.100 * 0.20 * 25.13 ** 2  # ≈ 12.63 N
    assert abs(f - expected) < 0.01


def test_imbalance_force_scales_quadratically_with_omega():
    f1 = imbalance_force_amplitude(50.0, 0.20, 10.0)
    f2 = imbalance_force_amplitude(50.0, 0.20, 20.0)
    assert abs(f2 / f1 - 4.0) < 1e-9


# ---------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------

def test_bandpass_passes_in_band():
    fs = 2000.0
    t = np.arange(0, 5, 1 / fs)
    sig = np.sin(2 * np.pi * 4 * t)
    filt = bandpass_filter(sig, fs, 2, 10)
    # Should still be a 4 Hz sinusoid with amplitude close to 1
    assert abs(np.std(filt) - np.std(sig)) / np.std(sig) < 0.02


def test_bandpass_rejects_dc_and_high_freq():
    fs = 2000.0
    t = np.arange(0, 5, 1 / fs)
    sig = 1.0 + np.sin(2 * np.pi * 50 * t)  # DC + 50 Hz
    filt = bandpass_filter(sig, fs, 2, 10)
    # After bandpass, amplitude should be drastically reduced
    assert np.std(filt) < 0.05


# ---------------------------------------------------------------------
# Phasor extraction
# ---------------------------------------------------------------------

def test_extract_phasor_amplitude_no_noise():
    fs = 2000.0
    t = np.arange(0, 5, 1 / fs)
    rpm = 240.0
    omega = 2 * np.pi * rpm / 60
    sig = 1.5 * np.cos(omega * t + np.deg2rad(30))

    phasor = extract_first_harmonic(sig, fs, rpm)
    assert abs(abs(phasor) - 1.5) < 0.01
    assert abs(angular_error_deg(np.degrees(np.angle(phasor)), 30.0)) < 0.5


def test_extract_phasor_zero_signal():
    fs = 2000.0
    sig = np.zeros(10000)
    phasor = extract_first_harmonic(sig, fs, 240.0)
    assert abs(phasor) < 1e-9


# ---------------------------------------------------------------------
# Calibration identifies K correctly
# ---------------------------------------------------------------------

def test_calibration_recovers_K_no_noise():
    """With perfect signals, identify_K must reproduce the true K."""
    sensor_cfg = SensorConfig(noise_density_ug_rthz=1e-6)  # ~zero noise
    machine = MachineGeometry()
    wheel = WheelGeometry()
    rpm = 240.0
    fs = sensor_cfg.sample_rate_hz

    K_true = transfer_K_default(machine, wheel)

    def get_phasors(wA, aA, wB, aB):
        rng = np.random.default_rng(0)
        s_a, s_b, _ = generate_signal(
            wA, aA, wB, aB, rpm=rpm, duration_s=5.0,
            sensor_cfg=sensor_cfg, wheel=wheel,
            machine=machine, K=K_true, rng=rng,
        )
        f_rot = rpm / 60.0
        s_a_f = bandpass_filter(s_a, fs, max(0.5, f_rot - 2), f_rot + 6)
        s_b_f = bandpass_filter(s_b, fs, max(0.5, f_rot - 2), f_rot + 6)
        return (extract_first_harmonic(s_a_f, fs, rpm),
                extract_first_harmonic(s_b_f, fs, rpm))

    cal = CalibrationData(
        s_zero=get_phasors(0, 0, 0, 0),
        s_trial_a=get_phasors(50, 0, 0, 0),
        s_trial_b=get_phasors(0, 0, 50, 0),
        trial_radius_m=wheel.rim_radius_m,
        trial_rpm=rpm,
    )
    K_est = identify_K(cal, wheel)

    # Element-wise relative error must be <2% with no noise
    rel_err = np.abs((K_est - K_true) / K_true)
    assert np.max(rel_err) < 0.05, (
        f"K identification error too large:\n{rel_err}"
    )


# ---------------------------------------------------------------------
# End-to-end: 50 random cases
# ---------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_end_to_end_random_cases(seed):
    """Run a single launch with random imbalance, expect <0.8g and <3°."""
    rng = np.random.default_rng(seed)
    sensor_cfg = SensorConfig()
    machine = MachineGeometry()
    wheel = WheelGeometry(mass_kg=20.0)
    rpm = 240.0
    fs = sensor_cfg.sample_rate_hz

    K_true = transfer_K_default(machine, wheel)

    # Calibrate
    def get_phasors(wA, aA, wB, aB):
        s_a, s_b, _ = generate_signal(
            wA, aA, wB, aB, rpm=rpm, duration_s=5.0,
            sensor_cfg=sensor_cfg, wheel=wheel,
            machine=machine, K=K_true, rng=rng,
        )
        f_rot = rpm / 60.0
        s_a_f = bandpass_filter(s_a, fs, max(0.5, f_rot - 2), f_rot + 6)
        s_b_f = bandpass_filter(s_b, fs, max(0.5, f_rot - 2), f_rot + 6)
        return (extract_first_harmonic(s_a_f, fs, rpm),
                extract_first_harmonic(s_b_f, fs, rpm))

    s_zero = get_phasors(0, 0, 0, 0)
    cal = CalibrationData(
        s_zero=s_zero,
        s_trial_a=get_phasors(50, 0, 0, 0),
        s_trial_b=get_phasors(0, 0, 50, 0),
        trial_radius_m=wheel.rim_radius_m,
        trial_rpm=rpm,
    )
    K_est = identify_K(cal, wheel)

    # Random test case (10–60 g range)
    wA = rng.uniform(10, 60)
    aA = rng.uniform(0, 360)
    wB = rng.uniform(10, 60)
    aB = rng.uniform(0, 360)

    s_a, s_b, _ = generate_signal(
        wA, aA, wB, aB, rpm=rpm, duration_s=5.0,
        sensor_cfg=sensor_cfg, wheel=wheel,
        machine=machine, K=K_true, rng=rng,
    )
    res = run_pipeline(s_a, s_b, fs, rpm, K_est, wheel, s_zero=s_zero)

    assert abs(res.weight_a_g - wA) < 1.5, (
        f"Weight A error too large: {res.weight_a_g - wA:.2f}g"
    )
    assert abs(res.weight_b_g - wB) < 1.5
    assert abs(angular_error_deg(res.angle_a_deg, aA)) < 5.0
    assert abs(angular_error_deg(res.angle_b_deg, aB)) < 5.0


# ---------------------------------------------------------------------
# Angular error helper
# ---------------------------------------------------------------------

def test_angular_error_wraps():
    assert abs(angular_error_deg(359.0, 1.0) - (-2.0)) < 1e-9
    assert abs(angular_error_deg(1.0, 359.0) - 2.0) < 1e-9
    assert abs(angular_error_deg(180.0, 0.0)) == 180.0
    assert abs(angular_error_deg(0.0, 0.0)) < 1e-9
