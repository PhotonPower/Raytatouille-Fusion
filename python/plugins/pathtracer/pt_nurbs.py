"""NURBS curves and surfaces of the .nfcad format (docs/file-format.md), evaluated with NumPy:
points and first derivatives on a grid of parameters. No CAD, no nurbforge here."""

from __future__ import annotations

import numpy as np


def basis(degree: int, knots, u, derivative: bool = False):
    """B-spline basis functions at the parameters `u`: a dense matrix (len(u), n) with
    n = len(knots) - degree - 1, and its derivative with `derivative`."""
    k = np.asarray(knots, dtype=float)
    u = np.atleast_1d(np.asarray(u, dtype=float))
    n = len(k) - degree - 1
    if n < 1:
        raise ValueError("knot vector too short for the degree")
    span = np.clip(np.searchsorted(k, u, side="right") - 1, degree, n - 1)
    m = len(u)
    cur = np.zeros((m, len(k) - 1))               # degree 0: one per knot span
    cur[np.arange(m), span] = 1.0
    prev = cur
    for p in range(1, degree + 1):
        prev = cur
        cols = len(k) - 1 - p
        j = np.arange(cols)
        d1 = k[j + p] - k[j]
        d2 = k[j + p + 1] - k[j + 1]
        a = np.divide(1.0, d1, out=np.zeros(cols), where=d1 > 0)
        b = np.divide(1.0, d2, out=np.zeros(cols), where=d2 > 0)
        cur = (u[:, None] - k[j]) * a * prev[:, :cols] + (k[j + p + 1] - u[:, None]) * b * prev[:, 1:cols + 1]
        if derivative and p == degree:
            return cur, degree * (a * prev[:, :cols] - b * prev[:, 1:cols + 1])
    if derivative:                                # degree 0
        return cur[:, :n], np.zeros((m, n))
    return cur[:, :n]


def _points(g: dict, count: int) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(g["points"], dtype=float).reshape(-1, 3)
    w = np.asarray(g.get("weights") or [], dtype=float)
    if w.size == 0:
        w = np.ones(len(p))
    if len(p) != count or len(w) != count:
        raise ValueError("control points do not match the knot vectors")
    return p, w


def curve_points(g: dict, u) -> np.ndarray:
    """Points (len(u), 3) of a curve dict at the parameters u."""
    degree = int(g["degree"])
    n = len(g["knots"]) - degree - 1
    p, w = _points(g, n)
    b = basis(degree, g["knots"], u)
    return (b @ (p * w[:, None])) / (b @ w)[:, None]


def curve_domain(g: dict) -> tuple[float, float]:
    d = int(g["degree"])
    return float(g["knots"][d]), float(g["knots"][-d - 1])


def surface_domain(g: dict) -> tuple[float, float, float, float]:
    """(u0, u1, v0, v1) of a surface dict."""
    du, dv = int(g["degree_u"]), int(g["degree_v"])
    return (float(g["knots_u"][du]), float(g["knots_u"][-du - 1]),
            float(g["knots_v"][dv]), float(g["knots_v"][-dv - 1]))


def surface_grid(g: dict, us, vs):
    """Points and first derivatives of a surface dict on the grid us x vs:
    S, S_u, S_v with shape (len(us), len(vs), 3). Control points: index = i_u * num_v + i_v."""
    nu, nv = int(g["num_u"]), int(g["num_v"])
    p, w = _points(g, nu * nv)
    pw = np.concatenate([p * w[:, None], w[:, None]], axis=1).reshape(nu, nv, 4)
    bu, dbu = basis(int(g["degree_u"]), g["knots_u"], us, derivative=True)
    bv, dbv = basis(int(g["degree_v"]), g["knots_v"], vs, derivative=True)
    if bu.shape[1] != nu or bv.shape[1] != nv:
        raise ValueError("control points do not match the knot vectors")
    a = np.einsum("ai,bj,ijk->abk", bu, bv, pw)
    au = np.einsum("ai,bj,ijk->abk", dbu, bv, pw)
    av = np.einsum("ai,bj,ijk->abk", bu, dbv, pw)
    wgt = a[..., 3:4]
    s = a[..., :3] / wgt
    su = (au[..., :3] - au[..., 3:4] * s) / wgt
    sv = (av[..., :3] - av[..., 3:4] * s) / wgt
    return s, su, sv


def distinct_knots(degree: int, knots) -> np.ndarray:
    """The distinct knot values of the domain (span borders)."""
    k = np.asarray(knots, dtype=float)
    return np.unique(k[degree:len(k) - degree])


def local_basis(degree: int, knots: np.ndarray, u: np.ndarray):
    """The degree + 1 basis functions that are not zero at each parameter u, and their
    derivatives: (span, N, dN) with N[:, r] the function of control point span - degree + r
    (The NURBS Book, A2.2). For many points on a surface with many control points."""
    k = np.asarray(knots, dtype=float)
    u = np.asarray(u, dtype=float)
    n = len(k) - degree - 1
    span = np.clip(np.searchsorted(k, u, side="right") - 1, degree, n - 1)
    m = len(u)
    basis_ = np.zeros((m, degree + 1))
    basis_[:, 0] = 1.0
    lower = np.zeros((m, degree))                            # the functions of degree - 1
    left = np.zeros((m, degree + 1))
    right = np.zeros((m, degree + 1))
    for j in range(1, degree + 1):
        if j == degree:
            lower = basis_[:, :degree].copy()
        left[:, j] = u - k[span + 1 - j]
        right[:, j] = k[span + j] - u
        saved = np.zeros(m)
        for r in range(j):
            den = right[:, r + 1] + left[:, j - r]
            temp = np.divide(basis_[:, r], den, out=np.zeros(m), where=den != 0)
            basis_[:, r] = saved + right[:, r + 1] * temp
            saved = left[:, j - r] * temp
        basis_[:, j] = saved
    deriv = np.zeros((m, degree + 1))
    for r in range(degree + 1):
        if r > 0:
            den = k[span + r] - k[span + r - degree]
            deriv[:, r] += degree * np.divide(lower[:, r - 1], den, out=np.zeros(m), where=den != 0)
        if r < degree:
            den = k[span + r + 1] - k[span + r - degree + 1]
            deriv[:, r] -= degree * np.divide(lower[:, r], den, out=np.zeros(m), where=den != 0)
    return span, basis_, deriv


class Surface:
    """A surface dict prepared for points one by one: at(u, v) for arrays of parameters."""

    def __init__(self, g: dict):
        self.degree_u, self.degree_v = int(g["degree_u"]), int(g["degree_v"])
        self.knots_u = np.asarray(g["knots_u"], dtype=float)
        self.knots_v = np.asarray(g["knots_v"], dtype=float)
        nu, nv = int(g["num_u"]), int(g["num_v"])
        p, w = _points(g, nu * nv)
        self.pw = np.concatenate([p * w[:, None], w[:, None]], axis=1).reshape(nu, nv, 4)
        self.domain = surface_domain(g)

    def at(self, u: np.ndarray, v: np.ndarray):
        """Points and first derivatives at the parameters (u[i], v[i]): S, S_u, S_v, each (m, 3)."""
        su, nu, du = local_basis(self.degree_u, self.knots_u, u)
        sv, nv, dv = local_basis(self.degree_v, self.knots_v, v)
        iu = (su - self.degree_u)[:, None] + np.arange(self.degree_u + 1)
        iv = (sv - self.degree_v)[:, None] + np.arange(self.degree_v + 1)
        net = self.pw[iu[:, :, None], iv[:, None, :]]            # (m, degree_u + 1, degree_v + 1, 4)
        a = np.einsum("ma,mb,mabk->mk", nu, nv, net)
        au = np.einsum("ma,mb,mabk->mk", du, nv, net)
        av = np.einsum("ma,mb,mabk->mk", nu, dv, net)
        wgt = a[:, 3:4]
        s = a[:, :3] / wgt
        return s, (au[:, :3] - au[:, 3:4] * s) / wgt, (av[:, :3] - av[:, 3:4] * s) / wgt
