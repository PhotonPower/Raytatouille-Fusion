#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QString>

namespace nfcad::results {

class ResultStore;

/// Keyed results in the document (docs/file-format.md, "results"): the newest items of every key
/// (e.g. "workflow:<block>", the display windows of the node workflow) – images, curves, tables
/// and bars with their fingerprint. Number arrays are stored as base64 of their little-endian
/// bytes (float32 for image values, float64 for curves and bars, bytes for colours).
[[nodiscard]] QJsonArray saved_results(const ResultStore& store);

/// Puts saved results back into the store as one result set "Saved results" (source
/// "document"); entries it cannot read are skipped. Returns the number of items restored.
int restore_results(ResultStore& store, const QJsonArray& saved);

/// Fingerprint per key of the newest keyed items that have one: {key: stamp}.
[[nodiscard]] QJsonObject result_stamps(const ResultStore& store);

}  // namespace nfcad::results
