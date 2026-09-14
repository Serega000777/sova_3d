#include "geometry_core.hpp"

#include <cmath>

#include <Standard_Version.hxx>

namespace physical_ai::geometry {

bool BoundingBox::is_valid() const noexcept {
  const double values[] = {min_x, min_y, min_z, max_x, max_y, max_z};
  for (double v : values) {
    if (!std::isfinite(v)) return false;
  }
  return max_x >= min_x && max_y >= min_y && max_z >= min_z;
}

std::string_view version() noexcept { return GEOMETRY_SERVICE_VERSION; }

const char* occt_version() noexcept { return OCC_VERSION_COMPLETE; }

}  // namespace physical_ai::geometry
