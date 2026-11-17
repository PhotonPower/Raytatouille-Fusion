#pragma once

#include <QJsonObject>
#include <QString>

#include "document/document.hpp"

namespace nfcad::document {

/// Native document format `.nfcad`: UTF-8 JSON (docs/file-format.md). Version 2 adds groups
/// (model tree), entity attributes and group membership; version 1 files are still read.
/// Geometry is stored exactly (degrees, knots, control points, weights, trim loops).
inline constexpr int kNfcadFormatVersion = 2;

/// Writes the document. Returns an error message, empty on success. `extra`: further top-level
/// sections the application keeps with the document (e.g. "results", the kept results).
[[nodiscard]] QString save_nfcad(const Document& doc, const QString& path, const QJsonObject& extra = {});

/// Reads a file into `doc` (replacing its content). Returns an error message, empty on success.
/// `extra`, if given, receives the top-level sections the document itself does not hold.
[[nodiscard]] QString load_nfcad(Document& doc, const QString& path, QJsonObject* extra = nullptr);

// Exposed for tests.
[[nodiscard]] QJsonObject geometry_to_json(const Geometry& g);
[[nodiscard]] Geometry geometry_from_json(const QJsonObject& o);

}  // namespace nfcad::document
