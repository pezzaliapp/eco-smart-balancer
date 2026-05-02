"""
balance_sim.py
==============
CLI driver for the Eco-Smart Balancer simulator.

Usage examples
--------------

Single launch:
    python balance_sim.py --weight-a 20,45 --weight-b 10,200

Full parameter sweep with HTML report:
    python balance_sim.py --sweep --report

Realistic noise (compressor + thermal drift):
    python balance_sim.py --weight-a 30,90 --realistic-noise
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from balance_core import (
    CalibrationData,
    MachineGeometry,
    SensorConfig,
    WheelGeometry,
    angular_error_deg,
    extract_first_harmonic,
    bandpass_filter,
    generate_signal,
    identify_K,
    imbalance_force_amplitude,
    run_pipeline,
    transfer_K_default,
)


# =====================================================================
# Configuration
# =====================================================================

REPORTS_ROOT = Path(__file__).parent / "reports"
TARGET_WEIGHT_ERROR_G = 0.8
TARGET_ANGLE_ERROR_DEG = 3.0


# =====================================================================
# Calibration helper
# =====================================================================

def perform_virtual_calibration(rpm: float, sensor_cfg: SensorConfig,
                                wheel: WheelGeometry,
                                machine: MachineGeometry,
                                K_true: np.ndarray,
                                duration_s: float = 5.0,
                                rng: np.random.Generator | None = None
                                ) -> tuple[np.ndarray, tuple[complex, complex]]:
    """
    Run the 3-launch calibration procedure on the simulated machine.

    Returns
    -------
    K_estimated : 2x2 complex matrix identified from calibration
    s_zero : phasors of the zero launch (for taring)
    """
    rng = rng if rng is not None else np.random.default_rng(42)
    fs = sensor_cfg.sample_rate_hz

    def _run(weight_a, ang_a, weight_b, ang_b):
        s_a, s_b, _ = generate_signal(
            weight_a, ang_a, weight_b, ang_b,
            rpm=rpm, duration_s=duration_s,
            sensor_cfg=sensor_cfg, wheel=wheel,
            machine=machine, K=K_true, rng=rng,
        )
        f_rot = rpm / 60.0
        s_a_f = bandpass_filter(s_a, fs, max(0.5, f_rot - 2), f_rot + 6)
        s_b_f = bandpass_filter(s_b, fs, max(0.5, f_rot - 2), f_rot + 6)
        return (
            extract_first_harmonic(s_a_f, fs, rpm),
            extract_first_harmonic(s_b_f, fs, rpm),
        )

    s_zero = _run(0, 0, 0, 0)
    s_trial_a = _run(50, 0, 0, 0)
    s_trial_b = _run(0, 0, 50, 0)

    cal = CalibrationData(
        s_zero=s_zero,
        s_trial_a=s_trial_a,
        s_trial_b=s_trial_b,
        trial_mass_g=50.0,
        trial_radius_m=wheel.rim_radius_m,
        trial_rpm=rpm,
    )
    K_est = identify_K(cal, wheel)
    return K_est, s_zero


# =====================================================================
# Single test
# =====================================================================

@dataclass
class TestCase:
    weight_a_g: float
    angle_a_deg: float
    weight_b_g: float
    angle_b_deg: float
    rpm: float
    mass_kg: float


@dataclass
class TestResult:
    case: TestCase
    measured_a_g: float
    measured_a_deg: float
    measured_b_g: float
    measured_b_deg: float
    err_a_g: float
    err_a_deg: float
    err_b_g: float
    err_b_deg: float
    pass_target: bool


def run_single_test(case: TestCase, sensor_cfg: SensorConfig,
                    machine: MachineGeometry,
                    K_true: np.ndarray, K_est: np.ndarray,
                    s_zero: tuple[complex, complex],
                    realistic_noise: bool = False,
                    rng: np.random.Generator | None = None,
                    duration_s: float = 5.0) -> TestResult:
    rng = rng if rng is not None else np.random.default_rng()
    wheel = WheelGeometry(mass_kg=case.mass_kg)

    s_a, s_b, _ = generate_signal(
        case.weight_a_g, case.angle_a_deg,
        case.weight_b_g, case.angle_b_deg,
        rpm=case.rpm, duration_s=duration_s,
        sensor_cfg=sensor_cfg, wheel=wheel,
        machine=machine, K=K_true,
        realistic_noise=realistic_noise, rng=rng,
    )

    res = run_pipeline(
        s_a, s_b,
        fs=sensor_cfg.sample_rate_hz,
        rpm=case.rpm, K=K_est,
        wheel=wheel, s_zero=s_zero,
    )

    err_a_g = res.weight_a_g - case.weight_a_g
    err_b_g = res.weight_b_g - case.weight_b_g
    err_a_deg = angular_error_deg(res.angle_a_deg, case.angle_a_deg)
    err_b_deg = angular_error_deg(res.angle_b_deg, case.angle_b_deg)

    # If the imbalance is zero, angle is meaningless — skip angle check
    angle_check = True
    if case.weight_a_g >= 1.0:
        angle_check &= abs(err_a_deg) <= TARGET_ANGLE_ERROR_DEG
    if case.weight_b_g >= 1.0:
        angle_check &= abs(err_b_deg) <= TARGET_ANGLE_ERROR_DEG

    pass_target = (
        abs(err_a_g) <= TARGET_WEIGHT_ERROR_G and
        abs(err_b_g) <= TARGET_WEIGHT_ERROR_G and
        angle_check
    )

    return TestResult(
        case=case,
        measured_a_g=res.weight_a_g,
        measured_a_deg=res.angle_a_deg,
        measured_b_g=res.weight_b_g,
        measured_b_deg=res.angle_b_deg,
        err_a_g=err_a_g,
        err_a_deg=err_a_deg,
        err_b_g=err_b_g,
        err_b_deg=err_b_deg,
        pass_target=pass_target,
    )


# =====================================================================
# Sweep
# =====================================================================

def run_sweep(sensor_cfg: SensorConfig, machine: MachineGeometry,
              realistic_noise: bool = False,
              n_repeats: int = 5,
              rpm: float = 240.0,
              verbose: bool = True) -> pd.DataFrame:
    """Run a parametric sweep and return results as DataFrame."""
    masses = [10, 15, 20, 25, 30]
    weights = [5, 10, 20, 50, 100]
    angles = [0, 45, 90, 135, 180, 225, 270, 315]

    rng = np.random.default_rng(0)
    rows = []
    total = len(masses) * len(weights) * len(angles) * n_repeats
    done = 0

    # Calibrate once for the largest reference mass
    wheel_ref = WheelGeometry(mass_kg=20.0)
    K_true = transfer_K_default(machine, wheel_ref)
    K_est, s_zero = perform_virtual_calibration(
        rpm, sensor_cfg, wheel_ref, machine, K_true, rng=rng,
    )

    if verbose:
        print(f"[sweep] {total} tests planned, calibration complete")

    for m in masses:
        for w in weights:
            for a in angles:
                for rep in range(n_repeats):
                    case = TestCase(
                        weight_a_g=float(w),
                        angle_a_deg=float(a),
                        weight_b_g=float(w * 0.6),
                        angle_b_deg=float((a + 110) % 360),
                        rpm=rpm,
                        mass_kg=float(m),
                    )
                    res = run_single_test(
                        case, sensor_cfg, machine,
                        K_true=K_true, K_est=K_est, s_zero=s_zero,
                        realistic_noise=realistic_noise, rng=rng,
                    )
                    rows.append({
                        "mass_kg": case.mass_kg,
                        "weight_g": case.weight_a_g,
                        "angle_deg": case.angle_a_deg,
                        "rep": rep,
                        "err_a_g": res.err_a_g,
                        "err_b_g": res.err_b_g,
                        "err_a_deg": res.err_a_deg,
                        "err_b_deg": res.err_b_deg,
                        "abs_err_g": max(abs(res.err_a_g), abs(res.err_b_g)),
                        "abs_err_deg": max(abs(res.err_a_deg),
                                           abs(res.err_b_deg)),
                        "pass": res.pass_target,
                    })
                    done += 1
                    if verbose and done % 50 == 0:
                        print(f"[sweep] {done}/{total}")

    return pd.DataFrame(rows)


# =====================================================================
# Plots
# =====================================================================

def fig_to_b64(fig) -> str:
    """Render a matplotlib figure to base64 PNG for HTML embedding."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def plot_error_heatmap(df: pd.DataFrame) -> str:
    """Heatmap of weight error vs (mass, weight)."""
    pivot = df.groupby(["mass_kg", "weight_g"])["abs_err_g"].mean().unstack()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    im = ax.imshow(pivot.values, aspect="auto", origin="lower", cmap="RdYlGn_r")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{c:.0f}g" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{r:.0f}kg" for r in pivot.index])
    ax.set_xlabel("Imbalance weight")
    ax.set_ylabel("Wheel mass")
    ax.set_title("Mean absolute weight error (g)")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Error (g)")

    # Annotate cells
    for i, row in enumerate(pivot.index):
        for j, col in enumerate(pivot.columns):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    color="white" if val > pivot.values.max() / 2 else "black",
                    fontsize=9)
    return fig_to_b64(fig)


def plot_angle_rose(df: pd.DataFrame) -> str:
    """Polar histogram of angular errors."""
    errs = np.concatenate([df["err_a_deg"].values, df["err_b_deg"].values])
    fig, ax = plt.subplots(figsize=(5.5, 5.5),
                           subplot_kw={"projection": "polar"})
    bins = np.linspace(-np.pi, np.pi, 37)
    ax.hist(np.deg2rad(errs), bins=bins, color="#FFA726", edgecolor="white")
    ax.set_title("Distribution of angular errors")
    ax.set_theta_zero_location("N")
    return fig_to_b64(fig)


def plot_error_distribution(df: pd.DataFrame) -> str:
    """Histogram of weight errors with target line."""
    fig, ax = plt.subplots(figsize=(7, 4))
    errs = np.concatenate([df["err_a_g"].values, df["err_b_g"].values])
    ax.hist(errs, bins=50, color="#1F3A5F", edgecolor="white")
    ax.axvline(TARGET_WEIGHT_ERROR_G, color="red", linestyle="--",
               label=f"Target ±{TARGET_WEIGHT_ERROR_G}g")
    ax.axvline(-TARGET_WEIGHT_ERROR_G, color="red", linestyle="--")
    ax.set_xlabel("Weight error (g)")
    ax.set_ylabel("Count")
    ax.set_title("Weight error distribution across all tests")
    ax.legend()
    ax.grid(alpha=0.3)
    return fig_to_b64(fig)


def plot_pass_by_weight(df: pd.DataFrame) -> str:
    """Pass rate as a function of imbalance weight."""
    fig, ax = plt.subplots(figsize=(7, 4))
    grouped = df.groupby("weight_g")["pass"].mean() * 100
    ax.bar([f"{w:.0f}g" for w in grouped.index], grouped.values,
           color="#FFA726", edgecolor="white")
    ax.axhline(95, color="green", linestyle="--", label="95% target")
    ax.set_ylabel("Pass rate (%)")
    ax.set_xlabel("Imbalance weight")
    ax.set_title("% of tests meeting target ±0.8g and ±3°")
    ax.set_ylim(0, 105)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    return fig_to_b64(fig)


# =====================================================================
# HTML report
# =====================================================================

REPORT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Eco-Smart Balancer — Simulation Report</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    margin: 2rem auto; max-width: 980px; color: #222; line-height: 1.5;
    padding: 0 1rem;
  }}
  h1 {{ color: #1F3A5F; border-bottom: 3px solid #FFA726; padding-bottom: .3rem; }}
  h2 {{ color: #2E5C8A; margin-top: 2rem; }}
  .summary {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 1rem; margin: 1.5rem 0;
  }}
  .metric {{
    padding: 1rem; background: #f5f5f5; border-left: 4px solid #FFA726;
    border-radius: 4px;
  }}
  .metric .value {{ font-size: 1.7rem; font-weight: 700; color: #1F3A5F; }}
  .metric .label {{ font-size: .85rem; color: #555; text-transform: uppercase; }}
  .pass {{ color: #2c7a2c; }}
  .fail {{ color: #c0392b; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ padding: .5rem .8rem; border: 1px solid #ddd; text-align: left; }}
  th {{ background: #1F3A5F; color: white; }}
  img {{ max-width: 100%; margin: 1rem 0; border-radius: 4px;
         box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  .footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ddd;
             color: #777; font-size: .85rem; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px;
          font-family: "JetBrains Mono", Menlo, monospace; font-size: 90%; }}
</style>
</head>
<body>

<h1>🛞 Eco-Smart Balancer — Simulation Report</h1>
<p><em>Generated {timestamp}</em></p>

<h2>Test setup</h2>
<table>
  <tr><th>Sensors</th><td>2 × ADXL355 MEMS, {noise:.1f} µg/√Hz, {fs:.0f} Hz sample rate</td></tr>
  <tr><th>Launch RPM</th><td>{rpm:.0f}</td></tr>
  <tr><th>Acquisition</th><td>{duration:.1f} s, FFT 4096 with Hann window</td></tr>
  <tr><th>Tests run</th><td>{n_tests} (sweep over mass, weight, angle, repeats)</td></tr>
  <tr><th>Realistic noise</th><td>{realistic}</td></tr>
  <tr><th>Targets</th><td>±{tgt_g} g · ±{tgt_deg}° per plane</td></tr>
</table>

<h2>Summary metrics</h2>
<div class="summary">
  <div class="metric">
    <div class="value {pass_class}">{pass_rate:.1f}%</div>
    <div class="label">Pass rate</div>
  </div>
  <div class="metric">
    <div class="value">{mean_err_g:.2f} g</div>
    <div class="label">Mean weight error</div>
  </div>
  <div class="metric">
    <div class="value">{p95_err_g:.2f} g</div>
    <div class="label">P95 weight error</div>
  </div>
  <div class="metric">
    <div class="value">{p95_err_deg:.1f}°</div>
    <div class="label">P95 angle error</div>
  </div>
</div>

<h2>Conclusion</h2>
<p>{conclusion}</p>

<h2>Weight error vs (mass × imbalance)</h2>
<img src="data:image/png;base64,{img_heatmap}">

<h2>Pass rate by imbalance magnitude</h2>
<img src="data:image/png;base64,{img_passrate}">

<h2>Weight error distribution</h2>
<img src="data:image/png;base64,{img_dist}">

<h2>Angular error distribution</h2>
<img src="data:image/png;base64,{img_rose}">

<h2>Detailed statistics</h2>
{detail_table}

<div class="footer">
  Eco-Smart Balancer · open hardware project · CERN-OHL-S v2 / MIT
</div>

</body>
</html>
"""


def generate_report(df: pd.DataFrame, out_dir: Path,
                    sensor_cfg: SensorConfig, rpm: float,
                    duration: float, realistic: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")

    pass_rate = df["pass"].mean() * 100
    pass_class = "pass" if pass_rate >= 95 else "fail"
    mean_err_g = df["abs_err_g"].mean()
    p95_err_g = df["abs_err_g"].quantile(0.95)
    p95_err_deg = df["abs_err_deg"].quantile(0.95)

    # Conclusion text
    if pass_rate >= 95:
        conclusion = (
            f"<strong class='pass'>✅ The proposed sensor configuration "
            f"meets the precision target.</strong> "
            f"{pass_rate:.1f}% of {len(df)} simulated launches pass the "
            f"±{TARGET_WEIGHT_ERROR_G}g / ±{TARGET_ANGLE_ERROR_DEG}° "
            f"criteria. The hardware design can proceed with confidence."
        )
    elif pass_rate >= 80:
        conclusion = (
            f"<strong>⚠️ Borderline result.</strong> "
            f"{pass_rate:.1f}% pass rate suggests the configuration is "
            f"close to the limit. Consider longer acquisition (>5s), "
            f"better mechanical isolation, or a finer encoder."
        )
    else:
        conclusion = (
            f"<strong class='fail'>❌ Configuration does not meet target.</strong> "
            f"Only {pass_rate:.1f}% pass. Re-evaluate sensor choice, "
            f"signal processing, or mechanical design before building."
        )

    # Detail table by mass
    by_mass = df.groupby("mass_kg").agg(
        mean_err_g=("abs_err_g", "mean"),
        p95_err_g=("abs_err_g", lambda x: x.quantile(0.95)),
        max_err_g=("abs_err_g", "max"),
        pass_pct=("pass", lambda x: x.mean() * 100),
    ).round(3)
    detail_table = by_mass.to_html(classes=[], border=0, float_format="%.2f")

    html = REPORT_HTML_TEMPLATE.format(
        timestamp=timestamp,
        noise=sensor_cfg.noise_density_ug_rthz,
        fs=sensor_cfg.sample_rate_hz,
        rpm=rpm,
        duration=duration,
        n_tests=len(df),
        realistic="Yes (compressor + thermal drift)" if realistic else "No",
        tgt_g=TARGET_WEIGHT_ERROR_G,
        tgt_deg=TARGET_ANGLE_ERROR_DEG,
        pass_rate=pass_rate,
        pass_class=pass_class,
        mean_err_g=mean_err_g,
        p95_err_g=p95_err_g,
        p95_err_deg=p95_err_deg,
        conclusion=conclusion,
        img_heatmap=plot_error_heatmap(df),
        img_passrate=plot_pass_by_weight(df),
        img_dist=plot_error_distribution(df),
        img_rose=plot_angle_rose(df),
        detail_table=detail_table,
    )

    out_html = out_dir / "index.html"
    out_html.write_text(html, encoding="utf-8")

    # Also save raw data
    df.to_csv(out_dir / "results.csv", index=False)

    summary = {
        "timestamp": timestamp,
        "n_tests": int(len(df)),
        "pass_rate": float(pass_rate),
        "mean_err_g": float(mean_err_g),
        "p95_err_g": float(p95_err_g),
        "p95_err_deg": float(p95_err_deg),
        "rpm": rpm,
        "realistic_noise": realistic,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    return out_html


# =====================================================================
# CLI
# =====================================================================

def parse_pair(s: str) -> tuple[float, float]:
    """Parse '20,45' into (20.0, 45.0)."""
    parts = s.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Expected 'weight,angle', got {s!r}")
    return float(parts[0]), float(parts[1])


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Eco-Smart Balancer simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--mass", type=float, default=20.0,
                   help="Wheel mass in kg (default: 20)")
    p.add_argument("--rpm", type=float, default=240.0,
                   help="Launch RPM (default: 240)")
    p.add_argument("--weight-a", type=parse_pair, default=(20.0, 45.0),
                   metavar="g,deg",
                   help="Inner plane imbalance, e.g. 20,45 (default)")
    p.add_argument("--weight-b", type=parse_pair, default=(10.0, 200.0),
                   metavar="g,deg",
                   help="Outer plane imbalance, e.g. 10,200 (default)")
    p.add_argument("--duration", type=float, default=5.0,
                   help="Acquisition duration in seconds (default: 5)")
    p.add_argument("--noise-floor", type=float, default=1.0,
                   help="Noise multiplier (1.0 = ADXL355 nominal)")
    p.add_argument("--realistic-noise", action="store_true",
                   help="Add compressor 25 Hz and thermal drift")
    p.add_argument("--sweep", action="store_true",
                   help="Run full parametric sweep instead of single launch")
    p.add_argument("--repeats", type=int, default=5,
                   help="Repeats per case in sweep (default: 5)")
    p.add_argument("--report", action="store_true",
                   help="Generate HTML report (implied with --sweep)")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducibility")
    args = p.parse_args(argv)

    sensor_cfg = SensorConfig(
        noise_density_ug_rthz=25.0 * args.noise_floor,
    )
    machine = MachineGeometry()

    rng = np.random.default_rng(args.seed)

    if args.sweep:
        print(f"Running sweep: this may take 1–2 minutes...")
        df = run_sweep(
            sensor_cfg, machine,
            realistic_noise=args.realistic_noise,
            n_repeats=args.repeats,
            rpm=args.rpm,
        )
        # Save report
        out_dir = REPORTS_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = generate_report(
            df, out_dir, sensor_cfg, args.rpm,
            args.duration, args.realistic_noise,
        )
        print()
        print(f"📊 Sweep summary")
        print(f"  tests:      {len(df)}")
        print(f"  pass rate:  {df['pass'].mean() * 100:.1f}%")
        print(f"  mean err:   {df['abs_err_g'].mean():.2f} g · "
              f"{df['abs_err_deg'].mean():.1f}°")
        print(f"  P95 err:    {df['abs_err_g'].quantile(0.95):.2f} g · "
              f"{df['abs_err_deg'].quantile(0.95):.1f}°")
        print()
        print(f"📄 Report saved to: {report_path}")
        return 0

    # Single launch mode
    wheel = WheelGeometry(mass_kg=args.mass)
    K_true = transfer_K_default(machine, wheel)
    K_est, s_zero = perform_virtual_calibration(
        args.rpm, sensor_cfg, wheel, machine, K_true, rng=rng,
    )

    case = TestCase(
        weight_a_g=args.weight_a[0], angle_a_deg=args.weight_a[1],
        weight_b_g=args.weight_b[0], angle_b_deg=args.weight_b[1],
        rpm=args.rpm, mass_kg=args.mass,
    )
    res = run_single_test(
        case, sensor_cfg, machine,
        K_true=K_true, K_est=K_est, s_zero=s_zero,
        realistic_noise=args.realistic_noise, rng=rng,
        duration_s=args.duration,
    )

    print()
    print(f"🎯 Imbalance set:")
    print(f"   Plane A (inner): {case.weight_a_g:6.2f} g @ {case.angle_a_deg:6.1f}°")
    print(f"   Plane B (outer): {case.weight_b_g:6.2f} g @ {case.angle_b_deg:6.1f}°")
    print()
    print(f"📐 Measured by simulator:")
    print(f"   Plane A:         {res.measured_a_g:6.2f} g @ {res.measured_a_deg:6.1f}°")
    print(f"   Plane B:         {res.measured_b_g:6.2f} g @ {res.measured_b_deg:6.1f}°")
    print()
    print(f"❗ Errors:")
    print(f"   Plane A: {res.err_a_g:+.2f} g · {res.err_a_deg:+.1f}°")
    print(f"   Plane B: {res.err_b_g:+.2f} g · {res.err_b_deg:+.1f}°")
    print()
    if res.pass_target:
        print(f"✅ PASS — within target ±{TARGET_WEIGHT_ERROR_G}g · "
              f"±{TARGET_ANGLE_ERROR_DEG}°")
    else:
        print(f"❌ FAIL — exceeds target")
    return 0


# =====================================================================


if __name__ == "__main__":
    sys.exit(main())
