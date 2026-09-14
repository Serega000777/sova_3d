// geometry-service CLI.
//
//   geometry-service exec <plan.json> <out_dir> [--deflection MM]
//     Executes an OperationPlan v1, writes <out_dir>/<body>.brep + .stl and
//     prints a JSON result on stdout. Exit 0 on success, 1 on a structured
//     failure (JSON on stdout), 2 on usage error.
//   geometry-service version

#include <fstream>
#include <iostream>
#include <string>

#include <nlohmann/json.hpp>

#include "geometry_core.hpp"
#include "kernel.hpp"
#include "plan.hpp"

namespace geo = physical_ai::geometry;
using nlohmann::json;

namespace {

json bbox_json(const geo::BoundingBox& b) {
  return {{"min", {b.min_x, b.min_y, b.min_z}},
          {"max", {b.max_x, b.max_y, b.max_z}},
          {"size", {b.width(), b.depth(), b.height()}}};
}

int emit_failure(const std::string& code, const std::string& message, const std::string& op_id,
                 const std::string& op_type) {
  json out = {{"ok", false},
              {"error",
               {{"code", code},
                {"message", message},
                {"operation_id", op_id},
                {"operation_type", op_type}}}};
  std::cout << out.dump() << '\n';
  return 1;
}

int exec_plan(const std::string& plan_path, const std::string& out_dir, double deflection) {
  json document;
  {
    std::ifstream in(plan_path);
    if (!in) return emit_failure("plan_unreadable", "cannot open " + plan_path, "", "");
    try {
      document = json::parse(in);
    } catch (const json::exception& e) {
      return emit_failure("plan_not_json", e.what(), "", "");
    }
  }
  try {
    const geo::Plan plan = geo::parse_plan(document);
    const geo::ExecutionResult result = geo::execute(plan, deflection);
    geo::write_outputs(result, out_dir, deflection);

    json bodies = json::array();
    for (const auto& name : result.order) {
      const geo::BodyReport r = geo::report_body(name, result.bodies.at(name));
      bodies.push_back({{"name", r.name},
                        {"bbox_mm", bbox_json(r.bbox)},
                        {"volume_mm3", r.volume_mm3},
                        {"surface_area_mm2", r.surface_area_mm2},
                        {"solids", r.solids},
                        {"faces", r.faces},
                        {"edges", r.edges},
                        {"vertices", r.vertices},
                        {"valid", r.valid},
                        {"brep", name + ".brep"},
                        {"stl", name + ".stl"}});
    }
    json out = {{"ok", true},
                {"kernel", std::string("occt/") + geo::occt_version()},
                {"service_version", std::string(geo::version())},
                {"units", "mm"},
                {"executed", result.executed},
                {"bodies", bodies}};
    std::cout << out.dump() << '\n';
    return 0;
  } catch (const geo::PlanError& e) {
    return emit_failure("invalid_plan", e.message, e.operation_id, "");
  } catch (const geo::KernelError& e) {
    return emit_failure(e.code, e.message, e.operation_id, e.operation_type);
  } catch (const std::exception& e) {
    return emit_failure("internal_error", e.what(), "", "");
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 2 && std::string(argv[1]) == "version") {
    std::cout << "geometry-service " << geo::version() << " occt=" << geo::occt_version() << '\n';
    return 0;
  }
  if (argc < 4 || std::string(argv[1]) != "exec") {
    std::cerr << "usage: geometry-service exec <plan.json> <out_dir> [--deflection MM]\n";
    return 2;
  }
  double deflection = 0.05;
  for (int i = 4; i + 1 < argc; ++i) {
    if (std::string(argv[i]) == "--deflection") deflection = std::stod(argv[i + 1]);
  }
  return exec_plan(argv[2], argv[3], deflection);
}
