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
  // Only the edges on the body's bounding box: the outer corners, never the ones inside
  // pockets or holes (T-137).
  bool outer{false};
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
struct CreateSphere {
  double diameter_mm;
  Vec3 origin_mm{0, 0, 0};
};
struct CreateCone {
  double bottom_diameter_mm, top_diameter_mm, height_mm;
  Axis axis = Axis::Z;
  Vec3 origin_mm{0, 0, 0};
};
struct CreateTorus {
  double outer_diameter_mm, tube_diameter_mm;
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
// Hollow the body to a wall of `thickness_mm`; with `open_face` that face is removed so the
// hollow opens there (a box printed bottom-down), without it the void stays enclosed (F-007).
struct Shell {
  std::string target;
  double thickness_mm;
  std::optional<FaceSelector> open_face;
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
struct LinearPattern {
  std::string target;
  Axis axis;
  int count;
  double spacing_mm;
};
struct CircularPattern {
  std::string target;
  Axis axis;
  int count;
  double angle_deg;
  Vec3 origin_mm{0, 0, 0};
};
struct Mirror {
  std::string target;
  Axis axis;
  double offset_mm;
  bool keep_original;
};
struct SetDimensions {
  std::string target;
  std::optional<double> width_mm, depth_mm, height_mm;
};
struct SetParameter {
  std::string operation, parameter;
  double value;
};

using OperationBody = std::variant<CreateBox, CreateCylinder, CreateSphere, CreateCone, CreateTorus, Extrude,
                                   Boolean, Fillet, Chamfer, AddHole, Shell, Translate, Rotate,
                                   LinearPattern, CircularPattern, Mirror, SetDimensions,
                                   SetParameter>;

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
