#include <iostream>

#include "geometry_core.hpp"

int main() {
  namespace geo = physical_ai::geometry;
  std::cout << "geometry-service " << geo::version()
            << " occt=" << (geo::has_occt() ? "on" : "off") << '\n';
  return 0;
}
