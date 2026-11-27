#version 440

layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
layout(location = 2) in vec2 curvature;  // principal curvatures k1, k2

layout(location = 0) out vec3 v_normal;  // view space
layout(location = 1) out vec3 v_pos;     // view space
layout(location = 2) out vec2 v_curvature;

layout(std140, binding = 0) uniform buf {
  mat4 mvp;       // clip-space correction * projection * view
  mat4 view;      // world -> view (rigid, so it also transforms normals)
  vec4 color;     // entity colour
  vec4 params;    // x: 1 = shaded, 0 = flat; y: 1 = perspective
  vec4 analysis;  // x: kind (0 none, 1 zebra, 2 emap, 3 curvature, 4 draft); y: measure; z, w: range
  vec4 pull;      // xyz: pull direction (view space); w: draft angle (degrees) or zebra stripes
};

void main() {
  v_normal = mat3(view) * normal;
  v_pos = (view * vec4(position, 1.0)).xyz;
  v_curvature = curvature;
  gl_Position = mvp * vec4(position, 1.0);
}
