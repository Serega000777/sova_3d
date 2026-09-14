#pragma once

#include <string_view>

namespace physical_ai::geometry {

// All dimensions inside the kernel are canonical millimetres.
struct BoundingBox {
  double min_x{0}, min_y{0}, min_z{0};
  double max_x{0}, max_y{0}, max_z{0};

  [[nodiscard]] double width() const noexcept { return max_x - min_x; }
  [[nodiscard]] double depth() const noexcept { return max_y - min_y; }
  [[nodiscard]] double height() const noexcept { return max_z - min_z; }
  [[nodiscard]] bool is_valid() const noexcept;
};

[[nodiscard]] std::string_view version() noexcept;
[[nodiscard]] const char* occt_version() noexcept;

}  // namespace physical_ai::geometry
