#include "plan.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>

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
  if (!node[0].is_number() || !node[1].is_number() || !node[2].is_number()) {
    fail("vectors must contain numbers", id);
  }
  const Vec3 result = {node[0].get<double>(), node[1].get<double>(), node[2].get<double>()};
  if (!std::isfinite(result[0]) || !std::isfinite(result[1]) || !std::isfinite(result[2])) {
    fail("vectors must contain finite numbers", id);
  }
  return result;
}

Vec2 vec2(const json& node, const std::string& id) {
  if (!node.is_array() || node.size() != 2) fail("expected a 2-vector", id);
  if (!node[0].is_number() || !node[1].is_number()) {
    fail("vectors must contain numbers", id);
  }
  const Vec2 result = {node[0].get<double>(), node[1].get<double>()};
  if (!std::isfinite(result[0]) || !std::isfinite(result[1])) {
    fail("vectors must contain finite numbers", id);
  }
  return result;
}

double length(const Vec3& vector) {
  return std::sqrt(vector[0] * vector[0] + vector[1] * vector[1] +
                   vector[2] * vector[2]);
}

double dot(const Vec3& left, const Vec3& right) {
  return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

double cross_length(const Vec3& left, const Vec3& right) {
  const double x = left[1] * right[2] - left[2] * right[1];
  const double y = left[2] * right[0] - left[0] * right[2];
  const double z = left[0] * right[1] - left[1] * right[0];
  return std::sqrt(x * x + y * y + z * z);
}

void validate_profile_frame(const Vec3& normal, const Vec3& x_direction,
                            const std::string& id) {
  const double normal_length = length(normal);
  const double x_length = length(x_direction);
  if (normal_length <= 1e-9 || x_length <= 1e-9) {
    fail("profile plane directions must be nonzero", id);
  }
  if (std::abs(dot(normal, x_direction) / (normal_length * x_length)) > 1e-6) {
    fail("profile plane normal and x_direction must be perpendicular", id);
  }
}

void validate_analytic_frame(const Vec3& axis, const Vec3& reference,
                             const std::string& id) {
  if (std::abs(length(axis) - 1.0) > 1e-9 || std::abs(length(reference) - 1.0) > 1e-9) {
    fail("analytic surface directions must be unit length", id);
  }
  validate_profile_frame(axis, reference, id);
}

bool segments_intersect(const Vec2& a, const Vec2& b, const Vec2& c, const Vec2& d,
                        double epsilon) {
  const auto orientation = [](const Vec2& first, const Vec2& second, const Vec2& third) {
    return (second[0] - first[0]) * (third[1] - first[1]) -
           (second[1] - first[1]) * (third[0] - first[0]);
  };
  return std::max(std::min(a[0], b[0]), std::min(c[0], d[0])) <=
             std::min(std::max(a[0], b[0]), std::max(c[0], d[0])) + epsilon &&
         std::max(std::min(a[1], b[1]), std::min(c[1], d[1])) <=
             std::min(std::max(a[1], b[1]), std::max(c[1], d[1])) + epsilon &&
         orientation(a, b, c) * orientation(a, b, d) <= epsilon * epsilon &&
         orientation(c, d, a) * orientation(c, d, b) <= epsilon * epsilon;
}

void validate_analytic_boundary(AnalyticSurfacePatch& patch, const std::string& id) {
  constexpr double two_pi = 2.0 * std::numbers::pi;
  const double epsilon = std::max(patch.tolerance_mm, 1e-9);
  if (patch.boundary_uv.size() < 3 || patch.boundary_uv.size() > 128) {
    fail("analytic surface boundary_uv needs between 3 and 128 points", id);
  }
  const bool sphere = std::holds_alternative<SphericalSurface>(patch.surface);
  for (const Vec2& point : patch.boundary_uv) {
    if (!(point[0] >= 0.0 && point[0] < two_pi)) {
      fail("boundary_uv u must be in [0, 2*pi)", id);
    }
    if (sphere && !(point[1] >= -std::numbers::pi / 2.0 &&
                    point[1] <= std::numbers::pi / 2.0)) {
      fail("sphere boundary_uv v must be in [-pi/2, pi/2]", id);
    }
  }
  const Vec2& first = patch.boundary_uv.front();
  const Vec2& last = patch.boundary_uv.back();
  if (std::hypot(first[0] - last[0], first[1] - last[1]) <= epsilon) {
    fail("boundary_uv must not repeat its closing point", id);
  }

  int seam_crossings = 0;
  std::vector<Vec2> unwrapped{first};
  for (std::size_t index = 0; index < patch.boundary_uv.size(); ++index) {
    const Vec2& current = patch.boundary_uv[index];
    const Vec2& following = patch.boundary_uv[(index + 1) % patch.boundary_uv.size()];
    double du = following[0] - current[0];
    if (std::abs(du) > std::numbers::pi) {
      ++seam_crossings;
      du -= std::copysign(two_pi, du);
      if (std::abs(du) >= std::numbers::pi) {
        fail("boundary_uv seam crossing must take the shorter angular path", id);
      }
    }
    const double dv = following[1] - current[1];
    const bool same_u = std::abs(du) <= epsilon;
    const bool same_v = std::abs(dv) <= epsilon;
    if (same_u == same_v) {
      fail(same_u ? "boundary_uv has a zero-length edge"
                  : "boundary_uv edge is not axis-aligned",
           id);
    }
    if (index + 1 < patch.boundary_uv.size()) {
      unwrapped.push_back({unwrapped.back()[0] + du, following[1]});
    }
  }
  if (seam_crossings > 1) {
    fail("boundary_uv crosses the periodic seam more than once", id);
  }
  const auto [minimum, maximum] = std::minmax_element(
      unwrapped.begin(), unwrapped.end(),
      [](const Vec2& left, const Vec2& right) { return left[0] < right[0]; });
  const double angular_range = (*maximum)[0] - (*minimum)[0];
  if (!(angular_range > epsilon && angular_range <= two_pi + epsilon)) {
    fail("boundary_uv swept angular range must be in (0, 2*pi]", id);
  }
  double twice_area = 0.0;
  for (std::size_t index = 0; index < unwrapped.size(); ++index) {
    const Vec2& current = unwrapped[index];
    const Vec2& following = unwrapped[(index + 1) % unwrapped.size()];
    twice_area += current[0] * following[1] - current[1] * following[0];
  }
  if (!(twice_area > epsilon * epsilon)) {
    fail("boundary_uv swept angular range must be positive", id);
  }
  for (std::size_t left = 0; left < unwrapped.size(); ++left) {
    const std::size_t left_next = (left + 1) % unwrapped.size();
    for (std::size_t right = left + 1; right < unwrapped.size(); ++right) {
      const std::size_t right_next = (right + 1) % unwrapped.size();
      if (right == left + 1 || (left == 0 && right_next == 0)) continue;
      if (segments_intersect(unwrapped[left], unwrapped[left_next],
                             unwrapped[right], unwrapped[right_next], epsilon)) {
        fail("boundary_uv must not self-intersect", id);
      }
    }
  }
}

bool same_direction(const Vec3& left, const Vec3& right) {
  return dot(left, right) / (length(left) * length(right)) >= 1.0 - 1e-9;
}

double plane_offset(const Vec3& origin, const Vec3& normal) {
  return dot(origin, normal) / length(normal);
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
  if (kind == "edges_parallel_to") {
    return EdgesParallelTo{axis_of(node.value("axis", json()), id), node.value("outer", false)};
  }
  if (kind == "edges_of_face") return EdgesOfFace{face_selector(node.at("face"), id)};
  fail("unknown edge selector " + kind, id);
}

int point_index(const json& node, const char* key, std::size_t count, const std::string& id) {
  if (!node.contains(key) || !node[key].is_number_integer()) {
    fail(std::string("missing sketch point index ") + key, id);
  }
  const int index = node[key].get<int>();
  if (index < 0 || static_cast<std::size_t>(index) >= count) {
    fail(std::string(key) + " references a missing sketch point", id);
  }
  return index;
}

SketchConstraint sketch_constraint(const json& node, std::size_t count, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "fixed") return FixedConstraint{point_index(node, "point", count, id)};
  if (kind == "horizontal") {
    const int start = point_index(node, "start", count, id);
    const int end = point_index(node, "end", count, id);
    if (start == end) fail("horizontal constraint needs two different points", id);
    return HorizontalConstraint{start, end};
  }
  if (kind == "vertical") {
    const int start = point_index(node, "start", count, id);
    const int end = point_index(node, "end", count, id);
    if (start == end) fail("vertical constraint needs two different points", id);
    return VerticalConstraint{start, end};
  }
  if (kind == "coincident") {
    const int first = point_index(node, "first", count, id);
    const int second = point_index(node, "second", count, id);
    if (first == second) fail("coincident constraint needs two different points", id);
    return CoincidentConstraint{first, second};
  }
  if (kind == "distance") {
    const int start = point_index(node, "start", count, id);
    const int end = point_index(node, "end", count, id);
    if (start == end) fail("distance constraint needs two different points", id);
    return DistanceConstraint{start, end, positive_mm(node, "distance_mm", id)};
  }
  auto segment_pair = [&](auto make) -> SketchConstraint {
    const int first_start = point_index(node, "first_start", count, id);
    const int first_end = point_index(node, "first_end", count, id);
    const int second_start = point_index(node, "second_start", count, id);
    const int second_end = point_index(node, "second_end", count, id);
    if (first_start == first_end || second_start == second_end) {
      fail(kind + " constraint needs two nonzero segments", id);
    }
    return make(first_start, first_end, second_start, second_end);
  };
  if (kind == "equal_length") {
    return segment_pair([](int a, int b, int c, int d) -> SketchConstraint {
      return EqualLengthConstraint{a, b, c, d};
    });
  }
  if (kind == "parallel") {
    return segment_pair([](int a, int b, int c, int d) -> SketchConstraint {
      return ParallelConstraint{a, b, c, d};
    });
  }
  if (kind == "perpendicular") {
    return segment_pair([](int a, int b, int c, int d) -> SketchConstraint {
      return PerpendicularConstraint{a, b, c, d};
    });
  }
  fail("unknown sketch constraint " + kind, id);
}

SketchSegment sketch_segment(const json& node, const std::string& id) {
  const std::string kind = node.value("kind", "");
  if (kind == "line") return LineSketchSegment{};
  if (kind == "arc") {
    return ArcSketchSegment{vec2(node.at("center_mm"), id), node.value("clockwise", false)};
  }
  if (kind == "spline") {
    if (!node.contains("through_points_mm") || !node["through_points_mm"].is_array()) {
      fail("spline needs through_points_mm", id);
    }
    SplineSketchSegment segment;
    for (const auto& point : node["through_points_mm"]) {
      segment.through_points_mm.push_back(vec2(point, id));
    }
    if (segment.through_points_mm.empty() || segment.through_points_mm.size() > 30) {
      fail("spline needs between 1 and 30 interior interpolation points", id);
    }
    return segment;
  }
  if (kind == "nurbs") {
    if (!node.contains("control_points_mm") || !node["control_points_mm"].is_array()) {
      fail("NURBS needs control_points_mm", id);
    }
    NurbsSketchSegment segment;
    for (const auto& point : node["control_points_mm"]) {
      segment.control_points_mm.push_back(vec2(point, id));
    }
    if (segment.control_points_mm.empty() || segment.control_points_mm.size() > 30) {
      fail("NURBS needs between 1 and 30 interior control points", id);
    }
    if (!node.contains("degree") || !node["degree"].is_number_integer()) {
      fail("NURBS needs an integer degree", id);
    }
    segment.degree = node["degree"].get<int>();
    const std::size_t pole_count = segment.control_points_mm.size() + 2;
    if (segment.degree < 1 || segment.degree > 5 ||
        static_cast<std::size_t>(segment.degree) >= pole_count) {
      fail("NURBS degree must be between 1 and 5 and smaller than its pole count", id);
    }
    if (!node.contains("weights") || !node["weights"].is_array() ||
        node["weights"].size() != pole_count) {
      fail("NURBS weights must match its pole count", id);
    }
    for (const auto& weight_node : node["weights"]) {
      if (!weight_node.is_number()) fail("NURBS weights must be numbers", id);
      const double weight = weight_node.get<double>();
      if (!std::isfinite(weight) || !(weight > 0.0) || weight > 1'000'000.0) {
        fail("NURBS weights must be finite and positive", id);
      }
      segment.weights.push_back(weight);
    }
    if (!node.contains("knots") || !node["knots"].is_array() ||
        !node.contains("multiplicities") || !node["multiplicities"].is_array() ||
        node["knots"].size() != node["multiplicities"].size() ||
        node["knots"].size() < 2 || node["knots"].size() > 32) {
      fail("NURBS knots and multiplicities need the same bounded length", id);
    }
    int multiplicity_sum = 0;
    for (std::size_t index = 0; index < node["knots"].size(); ++index) {
      if (!node["knots"][index].is_number() ||
          !node["multiplicities"][index].is_number_integer()) {
        fail("NURBS knots and multiplicities have invalid values", id);
      }
      const double knot = node["knots"][index].get<double>();
      const int multiplicity = node["multiplicities"][index].get<int>();
      if (!std::isfinite(knot) || std::abs(knot) > 1'000'000.0 ||
          (index > 0 && !(segment.knots.back() < knot))) {
        fail("NURBS knots must be finite and strictly increasing", id);
      }
      if (multiplicity < 1 || multiplicity > 6) {
        fail("NURBS multiplicities out of range", id);
      }
      segment.knots.push_back(knot);
      segment.multiplicities.push_back(multiplicity);
      multiplicity_sum += multiplicity;
    }
    if (segment.multiplicities.front() != segment.degree + 1 ||
        segment.multiplicities.back() != segment.degree + 1) {
      fail("NURBS endpoint multiplicities must equal degree + 1", id);
    }
    for (std::size_t index = 1; index + 1 < segment.multiplicities.size(); ++index) {
      if (segment.multiplicities[index] > segment.degree) {
        fail("NURBS interior multiplicities must not exceed its degree", id);
      }
    }
    if (multiplicity_sum != static_cast<int>(pole_count) + segment.degree + 1) {
      fail("NURBS multiplicities do not match its poles and degree", id);
    }
    return segment;
  }
  fail("unknown sketch segment " + kind, id);
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
  if (kind == "sketch") {
    SketchProfile profile;
    for (const auto& point : node.at("points_mm")) profile.points_mm.push_back(vec2(point, id));
    if (profile.points_mm.size() < 2 || profile.points_mm.size() > 128) {
      fail("sketch needs between 2 and 128 points", id);
    }
    profile.tolerance_mm = node.value("tolerance_mm", 1e-5);
    if (!(profile.tolerance_mm > 0.0 && profile.tolerance_mm <= 0.1)) {
      fail("sketch tolerance_mm out of range", id);
    }
    if (!node.contains("segments") || node["segments"].is_null()) {
      if (profile.points_mm.size() < 3) fail("implicit line sketch needs at least 3 points", id);
      profile.segments.assign(profile.points_mm.size(), LineSketchSegment{});
    } else {
      if (!node["segments"].is_array() || node["segments"].size() != profile.points_mm.size()) {
        fail("sketch segments must match the number of boundary points", id);
      }
      for (const auto& segment : node["segments"]) {
        profile.segments.push_back(sketch_segment(segment, id));
      }
    }
    for (std::size_t index = 0; index < profile.segments.size(); ++index) {
      const Vec2& start = profile.points_mm[index];
      const Vec2& end = profile.points_mm[(index + 1) % profile.points_mm.size()];
      const double chord = std::hypot(start[0] - end[0], start[1] - end[1]);
      if (chord <= profile.tolerance_mm) fail("sketch segment endpoints must be distinct", id);
      const auto* arc = std::get_if<ArcSketchSegment>(&profile.segments[index]);
      const auto* spline = std::get_if<SplineSketchSegment>(&profile.segments[index]);
      const auto* nurbs = std::get_if<NurbsSketchSegment>(&profile.segments[index]);
      if (spline != nullptr) {
        Vec2 previous = start;
        for (const auto& point : spline->through_points_mm) {
          if (std::hypot(previous[0] - point[0], previous[1] - point[1]) <=
              profile.tolerance_mm) {
            fail("spline interpolation points must be distinct", id);
          }
          previous = point;
        }
        if (std::hypot(previous[0] - end[0], previous[1] - end[1]) <=
            profile.tolerance_mm) {
          fail("spline interpolation points must be distinct", id);
        }
      }
      if (nurbs != nullptr) {
        Vec2 previous = start;
        for (const auto& point : nurbs->control_points_mm) {
          if (std::hypot(previous[0] - point[0], previous[1] - point[1]) <=
              profile.tolerance_mm) {
            fail("NURBS control points must be consecutively distinct", id);
          }
          previous = point;
        }
        if (std::hypot(previous[0] - end[0], previous[1] - end[1]) <=
            profile.tolerance_mm) {
          fail("NURBS control points must be consecutively distinct", id);
        }
      }
      if (arc == nullptr) continue;
      const double start_radius = std::hypot(start[0] - arc->center_mm[0],
                                             start[1] - arc->center_mm[1]);
      const double end_radius = std::hypot(end[0] - arc->center_mm[0],
                                           end[1] - arc->center_mm[1]);
      if (std::min(start_radius, end_radius) <= profile.tolerance_mm) {
        fail("arc endpoints must differ from its center", id);
      }
      if (std::abs(start_radius - end_radius) > profile.tolerance_mm) {
        fail("arc endpoints must have the same radius", id);
      }
    }
    for (const auto& constraint : node.value("constraints", json::array())) {
      profile.constraints.push_back(sketch_constraint(constraint, profile.points_mm.size(), id));
    }
    return profile;
  }
  fail("unknown profile " + kind, id);
}

std::string ref(const json& op, const char* key, const std::string& id) {
  if (!op.contains(key) || !op[key].is_string()) fail(std::string("missing ") + key, id);
  return op[key].get<std::string>();
}

void nurbs_axis(const json& op, const char* prefix, int pole_count, int& degree,
                std::vector<double>& knots, std::vector<int>& multiplicities,
                const std::string& id) {
  const std::string degree_key = std::string(prefix) + "_degree";
  const std::string knots_key = std::string(prefix) + "_knots";
  const std::string multiplicities_key = std::string(prefix) + "_multiplicities";
  if (!op.contains(degree_key) || !op[degree_key].is_number_integer()) {
    fail("NURBS surface needs an integer " + degree_key, id);
  }
  degree = op[degree_key].get<int>();
  if (degree < 1 || degree > 5 || degree >= pole_count) {
    fail("NURBS surface " + std::string(prefix) +
             " degree must be between 1 and 5 and smaller than its pole count",
         id);
  }
  if (!op.contains(knots_key) || !op[knots_key].is_array() ||
      !op.contains(multiplicities_key) || !op[multiplicities_key].is_array() ||
      op[knots_key].size() != op[multiplicities_key].size() ||
      op[knots_key].size() < 2 || op[knots_key].size() > 16) {
    fail("NURBS surface " + std::string(prefix) +
             " knots and multiplicities need the same bounded length",
         id);
  }
  int sum = 0;
  for (std::size_t index = 0; index < op[knots_key].size(); ++index) {
    if (!op[knots_key][index].is_number() ||
        !op[multiplicities_key][index].is_number_integer()) {
      fail("NURBS surface knots and multiplicities have invalid values", id);
    }
    const double knot = op[knots_key][index].get<double>();
    const int multiplicity = op[multiplicities_key][index].get<int>();
    if (!std::isfinite(knot) || std::abs(knot) > 1'000'000.0 ||
        (index > 0 && !(knots.back() < knot))) {
      fail("NURBS surface knots must be finite and strictly increasing", id);
    }
    if (multiplicity < 1 || multiplicity > 6) {
      fail("NURBS surface multiplicities out of range", id);
    }
    knots.push_back(knot);
    multiplicities.push_back(multiplicity);
    sum += multiplicity;
  }
  if (multiplicities.front() != degree + 1 || multiplicities.back() != degree + 1) {
    fail("NURBS surface endpoint multiplicities must equal degree + 1", id);
  }
  for (std::size_t index = 1; index + 1 < multiplicities.size(); ++index) {
    if (multiplicities[index] > degree) {
      fail("NURBS surface interior multiplicities must not exceed its degree", id);
    }
  }
  if (sum != pole_count + degree + 1) {
    fail("NURBS surface multiplicities do not match its poles and degree", id);
  }
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
  if (type == "create_sphere") {
    return CreateSphere{positive_mm(op, "diameter_mm", id),
                        vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "create_cone") {
    const double top = op.value("top_diameter_mm", 0.0);
    if (top < 0.0 || top > 10000.0) fail("top_diameter_mm out of range", id);
    return CreateCone{positive_mm(op, "bottom_diameter_mm", id), top,
                      positive_mm(op, "height_mm", id),
                      axis_of(op.value("axis", json()), id),
                      vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "create_torus") {
    const double outer = positive_mm(op, "outer_diameter_mm", id);
    const double tube = positive_mm(op, "tube_diameter_mm", id);
    if (2.0 * tube >= outer) fail("tube diameter must be less than half the outer diameter", id);
    return CreateTorus{outer, tube, axis_of(op.value("axis", json()), id),
                       vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "extrude") {
    const Vec3 normal = vec3(op.value("normal", json()), id, {0, 0, 1});
    const Vec3 x_direction = vec3(op.value("x_direction", json()), id, {1, 0, 0});
    validate_profile_frame(normal, x_direction, id);
    return Extrude{profile_of(op.at("profile"), id), positive_mm(op, "height_mm", id),
                   vec3(op.value("origin_mm", json()), id), normal, x_direction};
  }
  if (type == "loft") {
    Loft loft;
    for (const auto& node : op.at("sections")) {
      const Vec3 normal = vec3(node.value("normal", json()), id, {0, 0, 1});
      const Vec3 x_direction = vec3(node.value("x_direction", json()), id, {1, 0, 0});
      validate_profile_frame(normal, x_direction, id);
      loft.sections.push_back(ProfileSection{profile_of(node.at("profile"), id),
                                             vec3(node.value("origin_mm", json()), id),
                                             normal, x_direction});
    }
    if (loft.sections.size() < 2 || loft.sections.size() > 32) {
      fail("loft needs between 2 and 32 sections", id);
    }
    const ProfileSection& first = loft.sections.front();
    for (std::size_t index = 1; index < loft.sections.size(); ++index) {
      if (!same_direction(first.normal, loft.sections[index].normal) ||
          !same_direction(first.x_direction, loft.sections[index].x_direction)) {
        fail("loft sections must use one parallel profile frame", id);
      }
    }
    for (std::size_t left = 0; left < loft.sections.size(); ++left) {
      const double left_offset = plane_offset(loft.sections[left].origin_mm, first.normal);
      for (std::size_t right = left + 1; right < loft.sections.size(); ++right) {
        const double right_offset = plane_offset(loft.sections[right].origin_mm, first.normal);
        if (std::abs(left_offset - right_offset) <= 1e-9) {
          fail("loft sections must lie on different parallel planes", id);
        }
      }
    }
    loft.ruled = op.value("ruled", false);
    return loft;
  }
  if (type == "sweep") {
    Sweep sweep{profile_of(op.at("profile"), id), {}};
    for (const auto& point : op.at("path_mm")) sweep.path_mm.push_back(vec3(point, id));
    if (sweep.path_mm.size() < 2 || sweep.path_mm.size() > 256) {
      fail("sweep path needs between 2 and 256 points", id);
    }
    for (std::size_t index = 1; index < sweep.path_mm.size(); ++index) {
      if (sweep.path_mm[index - 1] == sweep.path_mm[index]) {
        fail("sweep path has a zero-length segment", id);
      }
    }
    return sweep;
  }
  if (type == "revolve") {
    const double angle = op.value("angle_deg", 360.0);
    if (!(angle > 0.0 && angle <= 360.0)) fail("revolve angle must be in (0, 360]", id);
    return Revolve{profile_of(op.at("profile"), id),
                   axis_of(op.value("axis", json()), id), angle,
                   vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "nurbs_surface") {
    NurbsSurface surface;
    if (!op.contains("control_points_mm") || !op["control_points_mm"].is_array() ||
        op["control_points_mm"].size() < 2 || op["control_points_mm"].size() > 16) {
      fail("NURBS surface needs between 2 and 16 U pole rows", id);
    }
    std::size_t v_poles = 0;
    for (const auto& row : op["control_points_mm"]) {
      if (!row.is_array() || row.size() < 2 || row.size() > 16 ||
          (v_poles != 0 && row.size() != v_poles)) {
        fail("NURBS surface control points must form a 2..16 by 2..16 grid", id);
      }
      v_poles = row.size();
      std::vector<Vec3> parsed_row;
      for (const auto& point : row) parsed_row.push_back(vec3(point, id));
      surface.control_points_mm.push_back(std::move(parsed_row));
    }
    if (!op.contains("weights") || !op["weights"].is_array() ||
        op["weights"].size() != surface.control_points_mm.size()) {
      fail("NURBS surface weights must match its control-point grid", id);
    }
    for (const auto& row : op["weights"]) {
      if (!row.is_array() || row.size() != v_poles) {
        fail("NURBS surface weights must match its control-point grid", id);
      }
      std::vector<double> parsed_row;
      for (const auto& item : row) {
        if (!item.is_number()) fail("NURBS surface weights must be numbers", id);
        const double weight = item.get<double>();
        if (!std::isfinite(weight) || !(weight > 0.0) || weight > 1'000'000.0) {
          fail("NURBS surface weights must be finite and positive", id);
        }
        parsed_row.push_back(weight);
      }
      surface.weights.push_back(std::move(parsed_row));
    }
    nurbs_axis(op, "u", static_cast<int>(surface.control_points_mm.size()),
               surface.u_degree, surface.u_knots, surface.u_multiplicities, id);
    nurbs_axis(op, "v", static_cast<int>(v_poles), surface.v_degree,
               surface.v_knots, surface.v_multiplicities, id);
    surface.thickness_mm = positive_mm(op, "thickness_mm", id);
    surface.tolerance_mm = op.value("tolerance_mm", 1e-5);
    if (!(surface.tolerance_mm > 0.0 && surface.tolerance_mm <= 0.1)) {
      fail("NURBS surface tolerance_mm out of range", id);
    }
    const Vec3 origin = surface.control_points_mm.front().front();
    std::vector<Vec3> vectors;
    for (const auto& row : surface.control_points_mm) {
      for (const auto& point : row) {
        vectors.push_back({point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]});
      }
    }
    bool spans_patch = false;
    for (std::size_t left = 0; left < vectors.size() && !spans_patch; ++left) {
      for (std::size_t right = left + 1; right < vectors.size(); ++right) {
        if (cross_length(vectors[left], vectors[right]) >
            surface.tolerance_mm * surface.tolerance_mm) {
          spans_patch = true;
          break;
        }
      }
    }
    if (!spans_patch) {
      fail("NURBS surface control net must span a two-dimensional patch", id);
    }
    return surface;
  }
  if (type == "analytic_surface_patch") {
    if (!op.contains("surface") || !op["surface"].is_object()) {
      fail("analytic_surface_patch needs a surface", id);
    }
    const json& node = op["surface"];
    const std::string kind = node.value("kind", "");
    AnalyticSurface surface;
    if (kind == "cylinder") {
      const Vec3 axis = vec3(node.value("axis_direction", json()), id);
      const Vec3 reference = vec3(node.value("reference_direction", json()), id);
      validate_analytic_frame(axis, reference, id);
      surface = CylindricalSurface{vec3(node.value("origin_mm", json()), id), axis, reference,
                                   positive_mm(node, "radius_mm", id)};
    } else if (kind == "cone") {
      const Vec3 axis = vec3(node.value("axis_direction", json()), id);
      const Vec3 reference = vec3(node.value("reference_direction", json()), id);
      validate_analytic_frame(axis, reference, id);
      const double half_angle = node.value("half_angle_deg", 0.0);
      if (!(half_angle > 0.0 && half_angle < 90.0)) {
        fail("half_angle_deg must be in (0, 90)", id);
      }
      surface = ConicalSurface{vec3(node.value("origin_mm", json()), id), axis, reference,
                               positive_mm(node, "radius_mm", id), half_angle};
    } else if (kind == "sphere") {
      const Vec3 axis = vec3(node.value("polar_axis_direction", json()), id);
      const Vec3 reference = vec3(node.value("reference_direction", json()), id);
      validate_analytic_frame(axis, reference, id);
      surface = SphericalSurface{vec3(node.value("center_mm", json()), id), axis, reference,
                                 positive_mm(node, "radius_mm", id)};
    } else {
      fail("unknown analytic surface kind " + kind, id);
    }
    AnalyticSurfacePatch patch{std::move(surface), {}, positive_mm(op, "thickness_mm", id),
                               op.value("tolerance_mm", 1e-5)};
    if (!(patch.tolerance_mm > 0.0 && patch.tolerance_mm <= 0.1)) {
      fail("analytic surface tolerance_mm out of range", id);
    }
    if (!op.contains("boundary_uv") || !op["boundary_uv"].is_array()) {
      fail("analytic surface boundary_uv must be an array", id);
    }
    for (const auto& point : op["boundary_uv"]) {
      patch.boundary_uv.push_back(vec2(point, id));
    }
    validate_analytic_boundary(patch, id);
    return patch;
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
  if (type == "shell") {
    Shell shell{ref(op, "target", id), positive_mm(op, "thickness_mm", id), std::nullopt};
    if (op.contains("open_face") && !op["open_face"].is_null()) {
      shell.open_face = face_selector(op["open_face"], id);
    }
    return shell;
  }
  if (type == "translate") return Translate{ref(op, "target", id), vec3(op.at("offset_mm"), id)};
  if (type == "rotate") {
    return Rotate{ref(op, "target", id), axis_of(op.value("axis", json()), id),
                  op.at("angle_deg").get<double>(), vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "linear_pattern") {
    const int count = op.at("count").get<int>();
    if (count < 2 || count > 100) fail("pattern count must be between 2 and 100", id);
    return LinearPattern{ref(op, "target", id), axis_of(op.value("axis", json()), id), count,
                         positive_mm(op, "spacing_mm", id)};
  }
  if (type == "circular_pattern") {
    const int count = op.at("count").get<int>();
    if (count < 2 || count > 100) fail("pattern count must be between 2 and 100", id);
    const double angle = op.value("angle_deg", 360.0);
    if (!(angle > 0.0 && angle <= 360.0)) fail("pattern angle must be in (0, 360]", id);
    return CircularPattern{ref(op, "target", id), axis_of(op.value("axis", json()), id), count,
                           angle, vec3(op.value("origin_mm", json()), id)};
  }
  if (type == "mirror") {
    return Mirror{ref(op, "target", id), axis_of(op.value("axis", json()), id),
                  op.value("offset_mm", 0.0), op.value("keep_original", true)};
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
// "origin_x_mm" -> component 0 of a vector parameter named "origin_mm"; -1 when it is not one.
int vector_component(const std::string& parameter, const std::string& stem) {
  if (parameter.size() != stem.size() + 5 || parameter.compare(0, stem.size(), stem) != 0) return -1;
  if (parameter.compare(stem.size(), 1, "_") != 0 || parameter.compare(stem.size() + 2, 3, "_mm") != 0) {
    return -1;
  }
  switch (parameter[stem.size() + 1]) {
    case 'x': return 0;
    case 'y': return 1;
    case 'z': return 2;
    default: return -1;
  }
}

bool apply_edit(Operation& target, const std::string& parameter, double value) {
  auto set = [&](double& field) {
    field = value;
    return true;
  };
  auto set_component = [&](auto& vector, const char* stem) -> bool {
    const int index = vector_component(parameter, stem);
    if (index < 0 || index >= static_cast<int>(vector.size())) return false;
    vector[static_cast<std::size_t>(index)] = value;
    return true;
  };
  return std::visit(
      [&](auto& body) -> bool {
        using T = std::decay_t<decltype(body)>;
        if constexpr (std::is_same_v<T, CreateBox>) {
          if (parameter == "width_mm") return set(body.width_mm);
          if (parameter == "depth_mm") return set(body.depth_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateCylinder>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateSphere>) {
          if (parameter == "diameter_mm") return set(body.diameter_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateCone>) {
          if (parameter == "bottom_diameter_mm") return set(body.bottom_diameter_mm);
          if (parameter == "top_diameter_mm") return set(body.top_diameter_mm);
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, CreateTorus>) {
          if (parameter == "outer_diameter_mm") return set(body.outer_diameter_mm);
          if (parameter == "tube_diameter_mm") return set(body.tube_diameter_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Extrude>) {
          if (parameter == "height_mm") return set(body.height_mm);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Revolve>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, NurbsSurface>) {
          if (parameter == "thickness_mm") return set(body.thickness_mm);
        } else if constexpr (std::is_same_v<T, AnalyticSurfacePatch>) {
          if (parameter == "thickness_mm") return set(body.thickness_mm);
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
          return set_component(body.position_mm, "position");
        } else if constexpr (std::is_same_v<T, Shell>) {
          if (parameter == "thickness_mm") return set(body.thickness_mm);
        } else if constexpr (std::is_same_v<T, Translate>) {
          return set_component(body.offset_mm, "offset");
        } else if constexpr (std::is_same_v<T, Rotate>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, LinearPattern>) {
          if (parameter == "spacing_mm") return set(body.spacing_mm);
        } else if constexpr (std::is_same_v<T, CircularPattern>) {
          if (parameter == "angle_deg") return set(body.angle_deg);
          return set_component(body.origin_mm, "origin");
        } else if constexpr (std::is_same_v<T, Mirror>) {
          if (parameter == "offset_mm") return set(body.offset_mm);
        }
        return false;
      },
      target.body);
}

// Positions may be zero or negative; sizes, radii and depths may not.
bool positional(const std::string& parameter) {
  return vector_component(parameter, "origin") >= 0 || vector_component(parameter, "position") >= 0 ||
         vector_component(parameter, "offset") >= 0 || parameter == "offset_mm";
}

}  // namespace

Plan resolve_parameter_edits(Plan plan) {
  std::vector<Operation> resolved;
  for (auto& op : plan.operations) {
    if (const auto* edit = std::get_if<SetParameter>(&op.body)) {
      bool applied = false;
      for (auto& earlier : resolved) {
        if (earlier.id == edit->operation) {
          if (!(edit->value > 0.0) && edit->parameter != "angle_deg" &&
              !positional(edit->parameter)) {
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
