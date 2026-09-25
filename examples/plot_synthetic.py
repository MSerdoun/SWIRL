"""Plot the synthetic end-member sample set (needs the `plot` extra: pip install -e .[plot])."""

from pathlib import Path

import matplotlib.pyplot as plt

import swirl
from swirl.synthetic import continuum, load_end_members

DATA = Path(__file__).parent / "data" / "synthetic"


def main() -> None:
    ems = load_end_members()
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for ax, key in zip(axes.flat, ["white_mica", "illite", "chlorite", "hematite"], strict=True):
        clean = swirl.read(DATA / f"{key}.txt")[0]
        noisy = swirl.read(DATA / f"{key}_noisy.txt")[0]
        ax.plot(noisy.wavelength, noisy.values, color="0.6", lw=0.7, label="noisy + ASD splice")
        ax.plot(clean.wavelength, clean.values, color="C0", lw=1.4, label="clean")
        ax.plot(
            clean.wavelength,
            continuum(ems[key], clean.wavelength),
            "k--",
            lw=0.8,
            label="generating continuum",
        )
        for band in ems[key].features:
            ax.axvline(band.center, color="C3", lw=0.6, alpha=0.6)
        for x in (1000, 1800):
            ax.axvline(x, color="C2", lw=0.5, ls=":")
        ax.set_title(ems[key].label, fontsize=10)
        ax.set_ylabel("Reflectance")
        ax.grid(alpha=0.2)
    axes[0, 0].legend(fontsize=8, loc="lower center")
    for ax in axes[1]:
        ax.set_xlabel("Wavelength (nm)")
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
