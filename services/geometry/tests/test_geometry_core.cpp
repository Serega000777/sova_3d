#include <cmath>
#include <cstdlib>
#include <iostream>

#include "geometry_core.hpp"

namespace {
int failures = 0;
void check(bool cond, const char* what) {
  if (!cond) {
    std::cerr << "FAIL: " << what << '\n';
    ++failures;
  }
}
}  // namespace

int main() {
  using physical_ai::geometry::BoundingBox;

  const BoundingBox box{0, 0, 0, 200, 100, 50};
  check(box.is_valid(), "well-formed box is valid");
  check(box.width() == 200.0 && box.depth() == 100.0 && box.height() == 50.0,
        "dimensions are exact in mm");

  const BoundingBox inverted{10, 0, 0, 0, 1, 1};
  check(!inverted.is_valid(), "inverted box is invalid");

  const BoundingBox nan_box{0, 0, 0, std::nan(""), 1, 1};
  check(!nan_box.is_valid(), "NaN coordinates are rejected");

  check(!physical_ai::geometry::version().empty(), "version string present");

  return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
