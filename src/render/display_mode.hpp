#pragma once

namespace nfcad::render {

/// Viewport display modes, see docs/rendering.md.
enum class DisplayMode { Wireframe, Surfaces, Shaded };

/// Surface analysis shown on the faces of every viewport (Zebra, EMap, CurvatureAnalysis,
/// DraftAngleAnalysis), drawn in the Surfaces and Shaded modes.
struct Analysis {
  enum class Kind { None, Zebra, EMap, Curvature, Draft };
  enum class Measure { Gaussian, Mean, Maximum, Minimum };  ///< curvature; max/min: |k| larger/smaller
  Kind kind = Kind::None;
  Measure measure = Measure::Gaussian;
  float lo = 0.0F, hi = 1.0F;          ///< curvature mapped blue (lo) … red (hi)
  float draft_angle = 3.0F;             ///< degrees: below this the face is red
  float direction[3] = {0.0F, 0.0F, 1.0F};  ///< pull direction (world)
  float stripes = 12.0F;                ///< zebra stripes per half turn
  bool operator==(const Analysis& o) const {
    return kind == o.kind && measure == o.measure && lo == o.lo && hi == o.hi && draft_angle == o.draft_angle &&
           direction[0] == o.direction[0] && direction[1] == o.direction[1] && direction[2] == o.direction[2] &&
           stripes == o.stripes;
  }
};

/// The value of a curvature measure from the principal curvatures.
inline float curvature_measure(Analysis::Measure m, float k1, float k2) {
  const float a1 = k1 < 0 ? -k1 : k1, a2 = k2 < 0 ? -k2 : k2;
  switch (m) {
    case Analysis::Measure::Gaussian: return k1 * k2;
    case Analysis::Measure::Mean: return 0.5F * (k1 + k2);
    case Analysis::Measure::Maximum: return a1 > a2 ? a1 : a2;
    case Analysis::Measure::Minimum: break;
  }
  return a1 < a2 ? a1 : a2;
}

}  // namespace nfcad::render
