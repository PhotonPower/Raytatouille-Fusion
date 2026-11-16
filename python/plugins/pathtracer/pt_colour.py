"""The colours of a camera image for the screen: the images of the wavelengths, each in the
colour the eye gives it, put together to one picture.

A wavelength becomes CIE 1931 XYZ (the observer in the fit of Wyman, Sloan and Shirley, JCGT 2
(2013) 1) and from there linear sRGB. The picture is balanced so that equal power on all
wavelengths of the scene is white (a lamp of five lines lights a white wall white), exposed by a
percentile of its luminance, and encoded as sRGB. It is a picture for the eye, not a measurement:
colours outside sRGB (every pure wavelength is) are cut to the nearest one inside.
"""

from __future__ import annotations

import math

import numpy as np

LUMINANCE = np.array([0.2126, 0.7152, 0.0722])                 # of linear sRGB


def colour_of(nm: float) -> tuple[float, float, float]:
    """Linear sRGB of light of one wavelength with unit power (may be negative: outside sRGB)."""
    def lobe(mu: float, s1: float, s2: float) -> float:
        return math.exp(-0.5 * ((nm - mu) / (s1 if nm < mu else s2)) ** 2)

    x = 1.056 * lobe(599.8, 37.9, 31.0) + 0.362 * lobe(442.0, 16.0, 26.7) - 0.065 * lobe(501.1, 20.4, 26.2)
    y = 0.821 * lobe(568.8, 46.9, 40.5) + 0.286 * lobe(530.9, 16.3, 31.1)
    z = 1.217 * lobe(437.0, 11.8, 36.0) + 0.681 * lobe(459.0, 26.0, 13.8)
    return (3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z,
            0.0557 * x - 0.2040 * y + 1.0570 * z)


def table(wavelengths) -> np.ndarray | None:
    """Red, green and blue of every wavelength (count, 3), balanced: equal power on all of them is
    white (1, 1, 1). Wavelengths that cannot make a white (two neighbouring lines, say) keep their
    own colours, with the luminance 1 for equal power. None: nothing of it is visible."""
    colours = np.array([colour_of(float(nm)) for nm in wavelengths], dtype=float).reshape(-1, 3)
    total = colours.sum(axis=0)
    luminance = float(total @ LUMINANCE)
    if not luminance > 1e-6:
        return None
    if total.min() > 0.05 * total.max():
        return colours / total
    return colours / luminance


def develop(channels, wavelengths, white: float = 99.5) -> np.ndarray | None:
    """The images of the wavelengths, `channels[k]` for `wavelengths[k]` (radiometric, any shape
    of an image), as one colour image of that shape with red, green, blue in 0 … 1 (sRGB) at the
    end. The luminance of the percentile `white` of the lit pixels is the brightest value; above
    it the colours run softly into white. None: no visible wavelength."""
    weights = table(wavelengths)
    if weights is None:
        return None
    rgb = np.maximum(np.tensordot(np.asarray(channels, dtype=float), weights, axes=(0, 0)), 0.0)
    luminance = rgb @ LUMINANCE
    lit = luminance[luminance > 0]
    level = float(np.percentile(lit, white)) if lit.size else 1.0
    rgb /= level if level > 0 else 1.0
    peak = rgb.max(axis=-1, keepdims=True)
    hue = rgb / np.maximum(peak, 1e-30)
    over = np.maximum(peak - 1.0, 0.0)
    rgb = np.where(peak > 1.0, hue + (1.0 - hue) * (1.0 - np.exp(-0.5 * over)), rgb)   # brighter than white
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)
