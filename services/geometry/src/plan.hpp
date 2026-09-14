#pragma once

// OperationPlan v1 as consumed by the kernel. Mirrors
// services/api/app/geometry/operations.py; the API validates plans before
// they get here, but parsing stays strict so a malformed plan is a
// structured error, never undefined behaviour.

#include <array>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include <nlohmann/json_fwd.hpp>

namespace physical_ai::geometry {

using Vec3 = std::array<double, 3>;
using Vec2 = std::array<double, 2>;
enum class Axis { X, Y, Z };

struct FaceByNormal {
  Axis axis;
  bool positive;
};
struct AllFaces {};
using FaceSelector = std::variant<FaceByNormal, AllFaces>;

struct AllEdges {};
struct EdgesParallelTo {
  Axis axis;
};
struct EdgesOfFace {
  FaceSelector face;
};
using EdgeSelector = std::variant<AllEdges, EdgesParallelTo, EdgesOfFace>;

struct RectangleProfile {
  double width_mm, depth_mm;
};
struct CircleProfile {
  double diameter_mm;
};
struct PolygonProfile {
  std::vector<Vec2> points_mm;
};
using Profile = std::variant<RectangleProfile, CircleProfile, PolygonProfile>;

struct CreateBox {
  double width_mm, depth_mm, height_mm;
  Vec3 origin_mm{0, 0, 0};
  bool centered = false;
};
struct CreateCylinder {
  double diameter_mm, height_mm;
  Axis axis = Axis::Z;
  Vec3 origin_mm{0, 0, 0};
};
struct Extrude {
  Profile profile;
  double height_mm;
  Vec3 origin_mm{0, 0, 0};
};
enum class BooleanOp { Cut, Fuse, Common };
struct Boolean {
  BooleanOp op;
  std::string target, tool;
};
struct Fillet {
  std::string target;
  EdgeSelector edges;
  double radius_mm;
};
struct Chamfer {
  std::string target;
  EdgeSelector edges;
  double distance_mm;
};
struct AddHole {
  std::string target;
  FaceSelector face;
  Vec2 position_mm;
  double diameter_mm;
  std::optional<double> depth_mm;  // nullopt = through
};
struct Translate {
  std::string target;
  Vec3 offset_mm;
};
struct Rotate {
  std::string target;
  Axis axis;
  double angle_deg;
  Vec3 origin_mm{0, 0, 0};
};
struct SetDimensions {
  std::string target;
  std::optional<double> width_mm, depth_mm, height_mm;
};
struct SetParameter {
  std::string operation, parameter;
  double value;
};

using OperationBody = std::variant<CreateBox, CreateCylinder, Extrude, Boolean, Fillet, Chamfer,
                                   AddHole, Translate, Rotate, SetDimensions, SetParameter>;

struct Operation {
  std::string id;
  std::string type;
  OperationBody body;
};

struct Plan {
  std::string goal;
  std::vector<Operation> operations;
  std::vector<std::string> expected_outputs;
};

struct PlanError {
  std::string message;
  std::string operation_id;  // empty when the plan itself is malformed
};

// Parses a v1 plan. Throws PlanError on any structural problem.
Plan parse_plan(const nlohmann::json& document);

// Applies every set_parameter to its target operation and removes it (T-040 replay).
Plan resolve_parameter_edits(Plan plan);

const char* axis_name(Axis axis) noexcept;

}  // namespace physical_ai::geometry
