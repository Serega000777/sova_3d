#include "plan.hpp"

#include <nlohmann/json.hpp>

namespace physical_ai::geometry {

using nlohmann::json;

namespace {

[[noreturn]] void fail(const std::string& message, const std::string& op_id = "") {
  throw PlanError{message, op_id};
}

double positive_mm(const json& op, const char* key, const std::string& id) {
  if (!op.contains(key) || !op[key].is_number()) fail(std::string("missing ") + key, id);
  const double value = op[key].get<double>();
  if (!(value > 0.0) || value > 10000.0) fail(std::string(key) + " out of range", id);
  return value;
}

Vec3 vec3(const json& node, const std::string& id, Vec3 fallback = {0, 0, 0}) {
  if (node.is_null()) return fallback;
  if (!node.is_array() || node.size() != 3) fail("expected a 3-vector", id);
  return {node[0].get<double>(), node[1].get<double>(), node[2].get<double>()};
}

Vec2 vec2(const json& node, const std::string& id) {
  if (!node.is_array() || node.size() != 2) fail("expected a 2-vector", id);
  return {node[0].get<double>(), node[1].get<double>()};
}

Axis axis_of(const json& node, const std::string& id, Axis fallback = Axis::Z) {
  if (node.is_null()) return fallback;
  const std::string name = node.get<std::string>();
  if (name == "x") return Axis::X;
  if (name == "y") return Axis::Y;
  if (name == "z") return Axis::Z;
  fail("unknown axis " + name, id);
}

FaceSelector face_selector(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "face_by_normal") {
    return FaceByNormal{axis_of(node.value("axis", json()), id), node.value("sign", "+") != "-"};
  }
  if (kind == "all_faces") return AllFaces{};
  fail("unknown face selector " + kind, id);
}

EdgeSelector edge_selector(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "all_edges") return AllEdges{};
  if (kind == "edges_parallel_to") return EdgesParallelTo{axis_of(node.value("axis", json()), id)};
  if (kind == "edges_of_face") return EdgesOfFace{face_selector(node.at("face"), id)};
  fail("unknown edge selector " + kind, id);
}

Profile profile_of(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "rectangle") {
    return RectangleProfile{positive_mm(node, "width_mm", id), positive_mm(node, "depth_mm", id)};
  }
  if (kind == "circle") return CircleProfile{positive_mm(node, "diameter_mm", id)};
  if (kind == "polygon") {
    PolygonProfile profile;
    for (const auto& point : node.at("points_mm")) profile.points_mm.push_back(vec2(point, id));
    if (profile.points_mm.size() < 3) fail("polygon needs at least 3 points", id);
    return profile;
  }
  fail("unknown profile " + kind, id);
}

std::string ref(const json& op, const char* key, const std::string& id) {
  if (!op.contains(key) || !op[key].is_string()) fail(std::string("missing ") + key, id);
  return op[key].get<std::string>();
}

OperationBody parse_body(const std::string& type, const json& op, const std::string& id) {
  if (type == "create_box") {
    return CreateBox{positive_mm(op, "width_mm", id), positive_mm(op, "depth_mm", id),
                     positive_mm(op, "height_mm", id), vec3(op.value("origin_mm", json()), id),
                     op.value("centered", false)};
  }
  if (type == "create_cylinder") {
    return CreateCylinder{positive_mm(op, "diameter_mm", id), positive_mm(op, "height_mm", id),
                          axis_of(op.value("axis", json()), id),
                          vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "extrude") {
    return Extrude{profile_of(op.at("profile"), id), positive_mm(op, "height_mm", id),
                   vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "boolean") {
    const std::string kind = op.value("op", "");
    BooleanOp boolean_op;
    if (kind == "cut") boolean_op = BooleanOp::Cut;
    else if (kind == "fuse") boolean_op = BooleanOp::Fuse;
    else if (kind == "common") boolean_op = BooleanOp::Common;
    else fail("unknown boolean op " + kind, id);
    return Boolean{boolean_op, ref(op, "target", id), ref(op, "tool", id)};
  }
  if (type == "fillet") {
    return Fillet{ref(op, "target", id), edge_selector(op.at("edges"), id),
                  positive_mm(op, "radius_mm", id)};
  }
  if (type == "chamfer") {
    return Chamfer{ref(op, "target", id), edge_selector(op.at("edges"), id),
                   positive_mm(op, "distance_mm", id)};
  }
  if (type == "add_hole") {
    AddHole hole{ref(op, "target", id), face_selector(op.at("face"), id),
                 vec2(op.at("position_mm"), id), positive_mm(op, "diameter_mm", id), std::nullopt};
    if (op.contains("depth_mm") && !op["depth_mm"].is_null()) {
      hole.depth_mm = positive_mm(op, "depth_mm", id);
    }
    return hole;
  }
  if (type == "translate") return Translate{ref(op, "target", id), vec3(op.at("offset_mm"), id)};
  if (type == "rotate") {
    return Rotate{ref(op, "target", id), axis_of(op.value("axis", json()), id),
                  op.at("angle_deg").get<double>(), vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "set_dimensions") {
    SetDimensions dims{ref(op, "target", id), std::nullopt, std::nullopt, std::nullopt};
    for (const char* key : {"width_mm", "depth_mm", "height_mm"}) {
      if (op.contains(key) && !op[key].is_null()) {
        const double value = positive_mm(op, key, id);
        if (std::string(key) == "width_mm") dims.width_mm = value;
        else if (std::string(key) == "depth_mm") dims.depth_mm = value;
        else dims.height_mm = value;
      }
    }
    if (!dims.width_mm && !dims.depth_mm && !dims.height_mm) fail("no dimension given", id);
    return dims;
  }
  if (type == "set_parameter") {
    return SetParameter{ref(op, "operation", id), ref(op, "parameter", id),
                        op.at("value").get<double>()};
  }
  fail("unsupported operation type " + type, id);
}

}  // namespace

Plan parse_plan(const json& document) {
  if (!document.is_object()) fail("plan must be an object");
  if (document.value("schema_version", 0) != 1) fail("unsupported plan schema_version");
  Plan plan;
  plan.goal = document.value("goal", "");
  for (const auto& node : document.value("expected_outputs", json::array())) {
    plan.expected_outputs.push_back(node.get<std::string>());
  }
  const auto& operations = document.value("operations", json::array());
  for (const auto& op : operations) {
    if (!op.is_object()) fail("operation must be an object");
    const std::string id = op.value("id", "");
    if (id.empty()) fail("operation without id");
    if (op.value("schema_version", 0) != 1) fail("unsupported operation schema_version", id);
    const std::string type = op.value("type", "");
    plan.operations.push_back(Operation{id, type, parse_body(type, op, id)});
  }
  return plan;
}

namespace {

// Numeric parameters that set_parameter may edit, per operation type.
bool apply_edit(Operation& target, const std::string& parameter, double value) {
  auto set = [&](double& field) {
    field = value;
    return true;
  };
  return std::visit(
      [&](auto& body) -> bool {
        using T = std::decay_t<decltype(body)>;
        if constexpr (std::is_same_v<T, CreateBox>) {
          if (parameter == "width_mm") return set(body.width_mm);
          if (parameter == "depth_mm") return set(body.depth_mm);
          if (parameter == "height_mm") return set(body.height_mm);
        } else if constexpr (std::is_same_v<T, CreateCylinder>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          if (parameter == "height_mm") return set(body.height_mm);
        } else if constexpr (std::is_same_v<T, Extrude>) {
          if (parameter == "height_mm") return set(body.height_mm);
        } else if constexpr (std::is_same_v<T, Fillet>) {
          if (parameter == "radius_mm") return set(body.radius_mm);
        } else if constexpr (std::is_same_v<T, Chamfer>) {
          if (parameter == "distance_mm") return set(body.distance_mm);
        } else if constexpr (std::is_same_v<T, AddHole>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          if (parameter == "depth_mm") {
            body.depth_mm = value;
            return true;
          }
        } else if constexpr (std::is_same_v<T, Rotate>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
        }
        return false;
      },
      target.body);
}

}  // namespace

Plan resolve_parameter_edits(Plan plan) {
  std::vector<Operation> resolved;
  for (auto& op : plan.operations) {
    if (const auto* edit = std::get_if<SetParameter>(&op.body)) {
      bool applied = false;
      for (auto& earlier : resolved) {
        if (earlier.id == edit->operation) {
          if (!(edit->value > 0.0) && edit->parameter != "angle_deg") {
            throw PlanError{"parameter value must be positive", op.id};
          }
          applied = apply_edit(earlier, edit->parameter, edit->value);
          break;
        }
      }
      if (!applied) throw PlanError{"cannot edit " + edit->parameter + " of " + edit->operation, op.id};
      continue;
    }
    resolved.push_back(std::move(op));
  }
  plan.operations = std::move(resolved);
  return plan;
}

const char* axis_name(Axis axis) noexcept {
  switch (axis) {
    case Axis::X: return "x";
    case Axis::Y: return "y";
    case Axis::Z: return "z";
  }
  return "?";
}

}  // namespace physical_ai::geometry
