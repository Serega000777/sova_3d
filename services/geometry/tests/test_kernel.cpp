// Golden tests for the OCCT executor (T-033..T-037, T-040).

#include <cmath>
#include <fstream>
#include <iostream>
#include <numbers>
#include <string>

#include <nlohmann/json.hpp>

#include "kernel.hpp"
#include "plan.hpp"

namespace geo = physical_ai::geometry;
using nlohmann::json;

namespace {

int failures = 0;

void check(bool cond, const std::string& what) {
  if (!cond) {
    std::cerr << "FAIL: " << what << '\n';
    ++failures;
  }
}

bool near(double a, double b, double rel = 1e-6) {
  return std::abs(a - b) <= rel * std::max({1.0, std::abs(a), std::abs(b)});
}

json op(const std::string& id, const std::string& type, json fields) {
  fields["id"] = id;
  fields["type"] = type;
  fields["schema_version"] = 1;
  return fields;
}

json plan(json operations) {
  return {{"schema_version", 1}, {"goal", "test"}, {"operations", std::move(operations)}};
}

geo::BodyReport run_single(const json& document, const std::string& body) {
  const geo::ExecutionResult result = geo::execute(geo::parse_plan(document));
  return geo::report_body(body, result.bodies.at(body));
}

void test_box() {
  const auto r = run_single(
      plan({op("b", "create_box", {{"width_mm", 200}, {"depth_mm", 100}, {"height_mm", 50}})}),
      "b");
  check(near(r.bbox.width(), 200) && near(r.bbox.depth(), 100) && near(r.bbox.height(), 50),
        "box bbox is 200x100x50");
  check(near(r.bbox.min_x, 0) && near(r.bbox.min_z, 0), "box corner at origin");
  check(near(r.volume_mm3, 1'000'000), "box volume");
  check(near(r.surface_area_mm2, 2 * (200 * 100 + 200 * 50 + 100 * 50)), "box area");
  check(r.solids == 1 && r.faces == 6 && r.edges == 12 && r.vertices == 8, "box topology");
  check(r.valid, "box valid");

  const auto c = run_single(plan({op("b", "create_box",
                                     {{"width_mm", 10},
                                      {"depth_mm", 10},
                                      {"height_mm", 10},
                                      {"centered", true},
                                      {"origin_mm", {5, 5, 5}}})}),
                            "b");
  check(near(c.bbox.min_x, 0) && near(c.bbox.max_x, 10), "centered box spans origin..10");
}

void test_cylinder() {
  const auto r = run_single(
      plan({op("c", "create_cylinder", {{"diameter_mm", 20}, {"height_mm", 30}})}), "c");
  check(near(r.bbox.width(), 20, 1e-4) && near(r.bbox.depth(), 20, 1e-4) &&
            near(r.bbox.height(), 30),
        "cylinder bbox");
  check(near(r.volume_mm3, std::numbers::pi * 100 * 30), "cylinder volume");
  check(r.solids == 1 && r.faces == 3, "cylinder topology");

  const auto y = run_single(plan({op("c", "create_cylinder",
                                     {{"diameter_mm", 20}, {"height_mm", 30}, {"axis", "y"}})}),
                            "c");
  check(near(y.bbox.depth(), 30) && near(y.bbox.width(), 20, 1e-4), "cylinder along y");
}

void test_extrude() {
  const auto r = run_single(
      plan({op("e", "extrude",
               {{"profile", {{"kind", "rectangle"}, {"width_mm", 30}, {"depth_mm", 20}}},
                {"height_mm", 10}})}),
      "e");
  check(near(r.volume_mm3, 6000), "rectangle extrude volume");
  const auto circle = run_single(
      plan({op("e", "extrude",
               {{"profile", {{"kind", "circle"}, {"diameter_mm", 10}}}, {"height_mm", 4}})}),
      "e");
  check(near(circle.volume_mm3, std::numbers::pi * 25 * 4), "circle extrude volume");
  const auto tri = run_single(
      plan({op("e", "extrude",
               {{"profile", {{"kind", "polygon"}, {"points_mm", {{0, 0}, {10, 0}, {0, 10}}}}},
                {"height_mm", 2}})}),
      "e");
  check(near(tri.volume_mm3, 100), "triangle extrude volume");
}

void test_boolean_and_replay() {
  const json organizer = plan({
      op("shell", "create_box", {{"width_mm", 100}, {"depth_mm", 50}, {"height_mm", 30}}),
      op("pocket", "create_box",
         {{"width_mm", 96}, {"depth_mm", 46}, {"height_mm", 27}, {"origin_mm", {2, 2, 3}}}),
      op("cut", "boolean", {{"op", "cut"}, {"target", "shell"}, {"tool", "pocket"}}),
  });
  const geo::ExecutionResult result = geo::execute(geo::parse_plan(organizer));
  check(result.bodies.count("shell") == 1 && result.bodies.count("pocket") == 0,
        "tool consumed by boolean");
  const auto r = geo::report_body("shell", result.bodies.at("shell"));
  check(near(r.volume_mm3, 100.0 * 50 * 30 - 96.0 * 46 * 27), "cut volume");
  check(r.solids == 1 && r.valid, "cut is one valid solid");
  check(r.faces == 11, "cut box has 11 faces after unify");  // 6 outer - top + 5 inner + rim

  // Replay with an edited parameter (T-038/T-040): deeper shell -> larger volume.
  json edited = organizer;
  edited["operations"].push_back(op("taller", "set_parameter",
                                    {{"operation", "shell"},
                                     {"parameter", "height_mm"},
                                     {"value", 40}}));
  const auto t = run_single(edited, "shell");
  check(near(t.volume_mm3, 100.0 * 50 * 40 - 96.0 * 46 * 27), "replayed volume after edit");

  const auto fuse = run_single(
      plan({op("a", "create_box", {{"width_mm", 10}, {"depth_mm", 10}, {"height_mm", 10}}),
            op("b", "create_box",
               {{"width_mm", 10}, {"depth_mm", 10}, {"height_mm", 10}, {"origin_mm", {5, 0, 0}}}),
            op("f", "boolean", {{"op", "fuse"}, {"target", "a"}, {"tool", "b"}})}),
      "a");
  check(near(fuse.volume_mm3, 1500) && fuse.faces == 6, "fuse merges coplanar faces");
}

void test_fillet_chamfer() {
  const auto r = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 20}, {"height_mm", 10}}),
            op("f", "fillet",
               {{"target", "b"},
                {"edges", {{"kind", "edges_parallel_to"}, {"axis", "z"}}},
                {"radius_mm", 2}})}),
      "b");
  const double removed = 4 * (4 - std::numbers::pi) * 10;  // four quarter-round corners
  check(near(r.volume_mm3, 4000 - removed, 1e-4), "vertical fillet volume");
  check(r.faces == 10, "4 cylindrical faces added");
  check(r.valid, "fillet valid");

  const auto c = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 20}, {"height_mm", 10}}),
            op("c", "chamfer",
               {{"target", "b"},
                {"edges",
                 {{"kind", "edges_of_face"},
                  {"face", {{"kind", "face_by_normal"}, {"axis", "z"}, {"sign", "+"}}}}},
                {"distance_mm", 1}})}),
      "b");
  // Four 1 mm x 1 mm triangular prisms (40 mm^3) minus the corner overlaps.
  check(c.volume_mm3 < 4000 - 38 && c.volume_mm3 > 4000 - 40, "top chamfer removes ~40 mm^3");
  check(c.faces == 10 && c.valid, "top chamfer adds 4 faces");
}

void test_hole() {
  const auto r = run_single(
      plan({op("b", "create_box", {{"width_mm", 40}, {"depth_mm", 20}, {"height_mm", 8}}),
            op("h", "add_hole",
               {{"target", "b"},
                {"face", {{"kind", "face_by_normal"}, {"axis", "z"}}},
                {"position_mm", {10, 10}},
                {"diameter_mm", 5}})}),
      "b");
  const double bore = std::numbers::pi * 2.5 * 2.5 * 8;
  check(near(r.volume_mm3, 6400 - bore, 1e-4), "through hole volume");
  check(r.faces == 7 && r.solids == 1 && r.valid, "through hole topology");

  const auto blind = run_single(
      plan({op("b", "create_box", {{"width_mm", 40}, {"depth_mm", 20}, {"height_mm", 8}}),
            op("h", "add_hole",
               {{"target", "b"},
                {"face", {{"kind", "face_by_normal"}, {"axis", "z"}}},
                {"position_mm", {10, 10}},
                {"diameter_mm", 5},
                {"depth_mm", 3}})}),
      "b");
  check(near(blind.volume_mm3, 6400 - std::numbers::pi * 2.5 * 2.5 * 3, 1e-4),
        "blind hole volume");
  check(blind.faces == 8, "blind hole adds wall + bottom");
}

void test_transforms() {
  const auto t = run_single(
      plan({op("b", "create_box", {{"width_mm", 10}, {"depth_mm", 10}, {"height_mm", 10}}),
            op("mv", "translate", {{"target", "b"}, {"offset_mm", {5, -5, 100}}})}),
      "b");
  check(near(t.bbox.min_x, 5) && near(t.bbox.min_y, -5) && near(t.bbox.min_z, 100),
        "translate moves bbox");

  const auto r = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 10}, {"height_mm", 5}}),
            op("rot", "rotate", {{"target", "b"}, {"axis", "z"}, {"angle_deg", 90}})}),
      "b");
  check(near(r.bbox.width(), 10, 1e-6) && near(r.bbox.depth(), 20, 1e-6), "rotate 90 about z");

  const auto s = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 10}, {"height_mm", 5}}),
            op("dim", "set_dimensions", {{"target", "b"}, {"width_mm", 40}, {"height_mm", 2.5}})}),
      "b");
  check(near(s.bbox.width(), 40) && near(s.bbox.depth(), 10) && near(s.bbox.height(), 2.5),
        "set_dimensions rescales chosen axes only");
  check(near(s.bbox.min_x, 0) && near(s.bbox.min_z, 0), "set_dimensions keeps anchor");

  // A non-uniform resize leaves B-spline geometry behind; selectors must still see a box,
  // otherwise every edit after a resize fails (T-055 feeding T-051).
  const auto after = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 10}, {"height_mm", 5}}),
            op("dim", "set_dimensions", {{"target", "b"}, {"width_mm", 40}, {"height_mm", 2.5}}),
            op("f", "fillet",
               {{"target", "b"},
                {"edges", {{"kind", "edges_parallel_to"}, {"axis", "z"}}},
                {"radius_mm", 1}}),
            op("h", "add_hole",
               {{"target", "b"},
                {"face", {{"kind", "face_by_normal"}, {"axis", "z"}, {"sign", "+"}}},
                {"position_mm", {20, 5}},
                {"diameter_mm", 4}})}),
      "b");
  check(after.valid, "fillet + hole after a resize stay valid");
  check(near(after.bbox.width(), 40) && near(after.bbox.height(), 2.5), "resized bbox survives");
  check(after.volume_mm3 < 40 * 10 * 2.5, "the hole and fillet removed material");

  const auto uniform = run_single(
      plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 10}, {"height_mm", 5}}),
            op("dim", "set_dimensions",
               {{"target", "b"}, {"width_mm", 40}, {"depth_mm", 20}, {"height_mm", 10}})}),
      "b");
  check(uniform.faces == 6 && uniform.edges == 12, "a uniform resize keeps the box topology");
  check(near(uniform.volume_mm3, 40 * 20 * 10), "uniform resize volume");
}

void test_structured_errors() {
  auto expect_error = [](const json& document, const std::string& code, const std::string& id) {
    try {
      geo::execute(geo::parse_plan(document));
      check(false, "expected kernel error " + code);
    } catch (const geo::KernelError& e) {
      check(e.code == code && e.operation_id == id, "error " + code + " from " + id +
                                                          " (got " + e.code + "/" +
                                                          e.operation_id + ")");
    } catch (const geo::PlanError& e) {
      check(code == "invalid_plan", "plan error: " + e.message);
    }
  };
  expect_error(plan({op("b", "create_box", {{"width_mm", 20}, {"depth_mm", 20}, {"height_mm", 10}}),
                     op("f", "fillet",
                        {{"target", "b"},
                         {"edges", {{"kind", "edges_parallel_to"}, {"axis", "z"}}},
                         {"radius_mm", 15}})}),
               "fillet_failed", "f");
  expect_error(plan({op("mv", "translate", {{"target", "ghost"}, {"offset_mm", {1, 0, 0}}})}),
               "unknown_body", "mv");
  expect_error(plan({op("c", "create_cylinder", {{"diameter_mm", 10}, {"height_mm", 10}}),
                     op("h", "add_hole",
                        {{"target", "c"},
                         {"face", {{"kind", "face_by_normal"}, {"axis", "x"}}},
                         {"position_mm", {0, 0}},
                         {"diameter_mm", 2}})}),
               "no_face_selected", "h");
  expect_error(plan({op("b", "create_box", {{"width_mm", 0}, {"depth_mm", 1}, {"height_mm", 1}})}),
               "invalid_plan", "b");
}

void test_fixture_plans() {
  for (const char* name : {"organizer-200x100x50.plan.json", "pipe-bracket.plan.json"}) {
    std::ifstream in(std::string(FIXTURES_DIR) + "/" + name);
    check(in.good(), std::string("fixture readable: ") + name);
    if (!in) continue;
    try {
      const geo::ExecutionResult result = geo::execute(geo::parse_plan(json::parse(in)));
      check(result.bodies.size() == 1, std::string("single body: ") + name);
      for (const auto& [body, shape] : result.bodies) {
        const auto r = geo::report_body(body, shape);
        check(r.valid && r.solids == 1, std::string("valid solid: ") + name);
        check(r.volume_mm3 > 0, std::string("positive volume: ") + name);
      }
    } catch (const geo::KernelError& e) {
      check(false, std::string(name) + " failed: " + e.code + " " + e.message + " @" +
                       e.operation_id);
    }
  }
}

}  // namespace

int run_kernel_tests() {
  test_box();
  test_cylinder();
  test_extrude();
  test_boolean_and_replay();
  test_fillet_chamfer();
  test_hole();
  test_transforms();
  test_structured_errors();
  test_fixture_plans();
  return failures;
}
