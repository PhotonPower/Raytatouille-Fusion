#pragma once

#include <QImage>
#include <QString>
#include <QStringList>

#include "results/result_types.hpp"

namespace nfcad::results {

/// Saving results to files (docs/plugins.md, "Saving results"): pictures as PNG, numbers as CSV
/// (comma separated, '.' as decimal point, UTF-8, 9 significant digits for floats).

/// The image as the Image window shows it, one pixel per sample, row 0 (y0) at the bottom: its
/// colours (a colour image), else the values through the colour map – linear over the range, or
/// logarithmic (`log`: four decades below the peak, as the window's "log").
/// `lo`/`hi` receive the colour range used (log10 values in log scale).
[[nodiscard]] QImage image_pixels(const Image& im, bool log = false, double* lo = nullptr, double* hi = nullptr);

/// A face field as a picture: its colours over (u, v), v upwards.
[[nodiscard]] QImage field_pixels(const FaceField& f);

/// The numbers of a result as CSV text:
/// - image, face field: '#' comment lines (name, unit, extent, labels), then the grid – one line
///   per row from y0 (v = 0) upwards, one column per x (u); `numpy.loadtxt(path, delimiter=",")`
///   reads it as an array [row, column];
/// - curve: a header line "x label,y label", then x,y per line;
/// - table: the column heads, then the rows;
/// - bars: "label,<y label>", then one bar per line;
/// - lines: "polyline,x,y,z" (and "value" if the points have values), one point per line,
///   NaN where a ray was lost; where the drawing is shown (moved / rotated in the views).
[[nodiscard]] QString to_csv(const ResultItem& item);

/// The file suffixes a result can be saved as: "png" and "csv" for images and face fields, "csv"
/// for the others.
[[nodiscard]] QStringList save_formats(const ResultItem& item);

/// Writes an item to `path`; the suffix (.png or .csv) picks the format. Images as PNG use the
/// linear colour scale unless `log`. False with a reason in `error`.
bool save_item(const ResultItem& item, const QString& path, QString* error = nullptr, bool log = false);

/// Writes every item of a run into the folder `dir`, named after the items (images and face
/// fields as PNG and CSV); returns the files written (paths), empty with `error` on failure.
QStringList save_set(const ResultSet& set, const QString& dir, QString* error = nullptr);

/// A file name for an item (its name without characters that file systems refuse) + suffix.
[[nodiscard]] QString file_name_for(const QString& name, const QString& suffix);

}  // namespace nfcad::results
