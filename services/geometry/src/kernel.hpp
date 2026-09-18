#pragma once

// Deterministic execution of an OperationPlan on Open CASCADE B-Rep bodies.

#include <map>
#include <string>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "geometry_core.hpp"
#include "plan.hpp"

namespace physical_ai::geometry {

struct BodyReport {
  std::string name;
  BoundingBox bbox;
  double volume_mm3 = 0;
  double surface_area_mm2 = 0;
  int solids = 0, faces = 0, edges = 0, vertices = 0;
  bool valid = false;
};

struct KernelError {
  std::string operation_id;
  std::string operation_type;
  std::string code;     // machine code, e.g. "boolean_failed", "no_edges_selected"
  std::string message;  // kernel detail, not for end users verbatim
};

struct ExecutionResult {
  std::map<std::string, TopoDS_Shape> bodies;  // ordered by name for deterministic output
  std::vector<std::string> order;              // creation order
  std::vector<std::string> executed;           // operation ids in execution order
};

// Executes every operation; throws KernelError on the first failure. A failed
// kernel operation never yields a corrupted body: the previous state is kept
// only in the caller's hands, nothing is written.
ExecutionResult execute(const Plan& plan, double linear_deflection_mm = 0.05);

BodyReport report_body(const std::string& name, const TopoDS_Shape& shape);

// Reads a STEP or IGES file into bodies (T-022). Untrusted input: any reader failure
// becomes a KernelError, never a crash, and the shapes are healed before use because
// exported CAD routinely arrives with open shells and tiny gaps.
ExecutionResult import_cad(const std::string& path, const std::string& format);

// Writes <dir>/<name>.brep and <dir>/<name>.stl (binary) for every body.
void write_outputs(const ExecutionResult& result, const std::string& dir,
                   double linear_deflection_mm = 0.05, double angular_deflection_rad = 0.35);

}  // namespace physical_ai::geometry
