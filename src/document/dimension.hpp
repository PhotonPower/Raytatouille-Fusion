#pragma once
/// @file dimension.hpp
/// Dimensions (docs/commands.md, "Dimensions"): curve entities of degree 1 whose control points
/// are the dimension's defining points, with their kind in the attribute kDimensionKey. The
/// polyline (extension and dimension lines) is drawn, picked, moved, hidden, deleted and saved
/// as any curve; the viewports add the arrows and the text. The value is measured from the
/// points whenever it is shown, so it follows Move, Rotate, Scale and grip edits.

#include <QString>
#include <QVariantMap>
#include <optional>
#include <vector>
#include <nurbforge/core/vec.hpp>

#include "document/entity.hpp"

namespace nfcad::document {

inline constexpr const char* kDimensionKey = "nfcad.dimension";
/// Text shown instead of the measured value; "<>" in it stands for the value. Empty or absent:
/// the value. Leaders: their text.
inline constexpr const char* kDimensionTextKey = "nfcad.dimension.text";
/// Ordinate dimensions: origin and unit axis of the coordinate shown, "x y z".
inline constexpr const char* kDimensionOriginKey = "nfcad.dimension.origin";
inline constexpr const char* kDimensionAxisKey = "nfcad.dimension.axis";

enum class DimensionKind { Linear, Aligned, Angle, ArcLength, Radius, Diameter, Ordinate, Leader };

/// Points of the arc of angle and arc-length dimensions (odd: one lies in the middle).
inline constexpr int kDimensionArcPoints = 33;

/// Control points of the polyline per kind:
///   Linear, Aligned   p1, a1, a2, p2: measured points and ends of the dimension line
///   Angle, ArcLength  s1, a1, (arc) ..., a2, s2: kDimensionArcPoints points a1 … a2 on the
///                     dimension arc, s1 / s2 the other ends of the extension lines (ArcLength:
///                     the ends of the measured arc, on its circle)
///   Radius            centre, point on the circle, end of the radial line, end of the landing
///                     (a short shoulder under the text)
///   Diameter          p1, p2 (through the centre), end of the line, end of the landing
///   Ordinate          measured point, text point
///   Leader            arrow tip, …, text point
[[nodiscard]] Entity make_dimension(DimensionKind kind, const std::vector<nf::Vec3>& points,
                                    const QString& text = {});

[[nodiscard]] QString dimension_kind_name(DimensionKind kind);
[[nodiscard]] std::optional<DimensionKind> dimension_kind(const Entity& e);

/// An arrow head at `tip`, pointing away from `from` (along from → tip).
struct DimensionArrow {
  nf::Vec3 tip;
  nf::Vec3 from;
};

/// What a viewport draws over the polyline.
struct DimensionView {
  DimensionKind kind = DimensionKind::Linear;
  std::vector<DimensionArrow> arrows;
  /// Text: centred above the line through `text_at` along `text_from` → `text_at` (on_line), or
  /// beyond `text_at` in that direction (at the end of a radius, diameter, ordinate or leader).
  nf::Vec3 text_at;
  nf::Vec3 text_from;
  bool on_line = true;
  QString text;
  double value = 0.0;  ///< length, angle in degrees or coordinate; 0 for leaders
  /// Unit normal of the dimension's plane where its points span one (views seeing it edge-on
  /// leave out arrows and text); empty for collinear points (radius, diameter, ordinate).
  std::optional<nf::Vec3> normal;
};

/// The view of a dimension entity; empty if `e` is no dimension or its points do not fit its kind.
[[nodiscard]] std::optional<DimensionView> dimension_view(const Entity& e);
[[nodiscard]] std::optional<DimensionView> dimension_view(const QVariantMap& attributes, const Geometry& g);

/// Measured value of the points of a dimension (as DimensionView::value).
[[nodiscard]] std::optional<double> dimension_value(DimensionKind kind, const std::vector<nf::Vec3>& points,
                                                    const QVariantMap& attributes = {});

/// Lengths with at most two decimals, angles with at most one, without trailing zeros.
[[nodiscard]] QString format_length(double v);
[[nodiscard]] QString format_angle(double degrees);

/// "x y z" ↔ point (attributes of ordinate dimensions).
[[nodiscard]] QString vec_text(const nf::Vec3& v);
[[nodiscard]] std::optional<nf::Vec3> vec_from_text(const QString& s);

}  // namespace nfcad::document
