// Meshes (docs/commands.md, "Meshes"): ShrinkWrap, one closed triangle mesh around the selected
// surfaces, polysurfaces and solids, whether they overlap, leave gaps or are open.
#include <QObject>
#include <algorithm>
#include <cmath>
#include <functional>
#include <nurbforge/mesh/shrink_wrap.hpp>

#include "commands/command_util.hpp"
#include "kernel/geometry_ops.hpp"

namespace nfcad::commands {

namespace {

using namespace util;

QString num(double v) { return QString::number(v, 'g', 4); }

/// A value with two significant digits (defaults that read well).
double rounded(double v) {
  if (!(v > 0)) return v;
  const double p = std::pow(10.0, std::floor(std::log10(v)) - 1);
  return std::round(v / p) * p;
}

/// ShrinkWrap: resolution (cell size of the grid, about the edge length and the accuracy), then
/// the offset of the hull from the objects. The objects stay.
class ShrinkWrapCommand : public Command {
 public:
  QString id() const override { return QStringLiteral("shrinkwrap"); }
  QString title() const override { return QObject::tr("Shrink wrap"); }
  QString prompt() const override {
    if (!resolution_) {
      return QObject::tr("Shrink wrap: resolution – cell size, about the edge length of the mesh (Enter: %1)")
          .arg(num(auto_resolution_));
    }
    return QObject::tr("Shrink wrap: offset from the objects (Enter: %1)").arg(num(default_offset()));
  }
  bool usesSelection() const override { return true; }
  bool begin(const std::vector<document::Entity>& selection) override {
    nf::Vec3 lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
    for (const document::Entity& e : selection) {
      const bool shell = std::holds_alternative<nf::Shell>(*e.geometry);
      std::vector<nf::TrimmedSurface> faces = kernel::faces_of(*e.geometry);
      if (faces.empty()) continue;
      if (!shell || !std::get<nf::Shell>(*e.geometry).is_closed()) open_ = true;
      for (nf::TrimmedSurface& f : faces) {
        for (const nf::Vec3& p : f.surface().control_points()) {
          lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
          hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
        }
        faces_.push_back(std::move(f));
      }
    }
    if (faces_.empty()) {
      message_ = QObject::tr("Shrink wrap: select surfaces, polysurfaces or solids");
      return false;
    }
    auto_resolution_ = rounded(std::max(nf::norm(hi - lo), 1e-9) / 100.0);
    return true;
  }
  Result point(const Point3&, const PlaneFrame&) override { return Result::Rejected; }
  Result number(double v) override {
    if (!resolution_) {
      if (!(v > 0)) return Result::Rejected;
      resolution_ = v;
      return Result::Continue;
    }
    if (v < 0) return Result::Rejected;
    return wrap(v);
  }
  Result finish() override {
    if (!resolution_) {
      resolution_ = auto_resolution_;
      return Result::Continue;
    }
    return wrap(default_offset());
  }

 private:
  /// Open input needs an offset of at least 0.75 × resolution (the kernel's limit).
  double default_offset() const { return open_ && resolution_ ? rounded(0.75 * *resolution_ * 1.01) : 0.0; }

  Result wrap(double offset) {
    try {
      nf::ShrinkWrapOptions o;
      o.offset = offset;
      o.max_nodes = 10'000'000;  // memory: a few hundred MB at most
      nf::TriangleMesh m = nf::shrink_wrap(faces_, *resolution_, o);
      message_ = QObject::tr("Shrink wrap: %1 triangles, %2, worst triangle quality %3")
                     .arg(m.triangles.size())
                     .arg(m.is_watertight() ? QObject::tr("closed") : QObject::tr("open"))
                     .arg(m.min_quality(), 0, 'f', 2);
      entities_.push_back(document::make_entity(std::move(m), QObject::tr("Shrink wrap")));
    } catch (const std::exception& e) {
      message_ = failure(title(), e);
      return Result::Rejected;
    }
    return Result::Done;
  }

  std::vector<nf::TrimmedSurface> faces_;
  bool open_ = false;
  double auto_resolution_ = 1.0;
  std::optional<double> resolution_;
};

struct Entry {
  const char* id;
  std::vector<const char*> aliases;
  std::function<std::unique_ptr<Command>()> make;
};

const std::vector<Entry>& registry() {
  static const std::vector<Entry> r = {
      {"shrinkwrap", {"shrink_wrap"}, [] { return std::make_unique<ShrinkWrapCommand>(); }},
  };
  return r;
}

}  // namespace

namespace detail {

std::unique_ptr<Command> create_mesh_command(const QString& n) {
  for (const Entry& e : registry()) {
    if (n == QLatin1String(e.id)) return e.make();
    for (const char* a : e.aliases) {
      if (n == QLatin1String(a)) return e.make();
    }
  }
  return nullptr;
}

QStringList mesh_command_ids() {
  QStringList out;
  for (const Entry& e : registry()) out << QString::fromLatin1(e.id);
  return out;
}

}  // namespace detail

}  // namespace nfcad::commands
