#version 440

layout(location = 0) in vec3 v_normal;
layout(location = 1) in vec3 v_pos;
layout(location = 2) in vec2 v_curvature;

layout(location = 0) out vec4 frag_color;

layout(std140, binding = 0) uniform buf {
  mat4 mvp;
  mat4 view;
  vec4 color;
  vec4 params;
  vec4 analysis;
  vec4 pull;
};

// blue (0) - cyan - green (0.5) - yellow - red (1)
vec3 ramp(float t) {
  t = clamp(t, 0.0, 1.0);
  return clamp(vec3(1.5 - abs(4.0 * t - 3.0), 1.5 - abs(4.0 * t - 2.0), 1.5 - abs(4.0 * t - 1.0)), 0.0, 1.0);
}

float measure(float k1, float k2) {
  int m = int(analysis.y + 0.5);
  if (m == 0) return k1 * k2;
  if (m == 1) return 0.5 * (k1 + k2);
  if (m == 2) return max(abs(k1), abs(k2));
  return min(abs(k1), abs(k2));
}

void main() {
  vec3 v = params.y > 0.5 ? normalize(-v_pos) : vec3(0.0, 0.0, 1.0);
  vec3 n0 = length(v_normal) > 1e-6 ? normalize(v_normal) : v;  // the surface's own normal
  vec3 n = n0;
  float side = 1.0;
  if (dot(n, v) < 0.0) {
    n = -n;
    side = 0.55;
  }
  int kind = int(analysis.x + 0.5);
  if (kind == 1) {  // zebra: stripes of the reflected view direction
    vec3 r = reflect(-v, n);
    float phi = asin(clamp(r.x, -1.0, 1.0));  // parallel bands across the view
    float s = smoothstep(0.47, 0.53, abs(fract(phi * pull.w / 3.14159265) - 0.5) * 2.0);
    frag_color = vec4(vec3(mix(0.06, 0.96, s)) * mix(0.8, 1.0, side), 1.0);
    return;
  }
  if (kind == 2) {  // environment map: a studio with a horizon and two soft boxes, reflected
    vec3 r = reflect(-v, n);
    vec3 sky = mix(vec3(0.62, 0.70, 0.80), vec3(0.95, 0.97, 1.0), clamp(r.y, 0.0, 1.0));
    vec3 ground = mix(vec3(0.20, 0.18, 0.16), vec3(0.05, 0.05, 0.05), clamp(-r.y, 0.0, 1.0));
    vec3 env = mix(ground, sky, smoothstep(-0.02, 0.02, r.y));
    env += vec3(1.2) * smoothstep(0.92, 0.97, dot(r, normalize(vec3(0.6, 0.5, 0.6))));
    env += vec3(0.8) * smoothstep(0.94, 0.98, dot(r, normalize(vec3(-0.7, 0.3, 0.4))));
    frag_color = vec4(clamp(env * mix(vec3(1.0), color.rgb, 0.25) * mix(0.8, 1.0, side), 0.0, 1.0), 1.0);
    return;
  }
  if (kind == 3) {  // curvature false colours
    float t = (measure(v_curvature.x, v_curvature.y) - analysis.z) / max(analysis.w - analysis.z, 1e-30);
    frag_color = vec4(ramp(t) * mix(0.75, 1.0, max(dot(n, v), 0.0)), 1.0);
    return;
  }
  if (kind == 4) {  // draft angle: of the own normal against the pull direction
    float a = degrees(asin(clamp(dot(n0, normalize(pull.xyz)), -1.0, 1.0)));
    vec3 c = a >= pull.w ? vec3(0.25, 0.80, 0.30) : a <= -pull.w ? vec3(0.25, 0.45, 0.95) : vec3(0.92, 0.25, 0.20);
    frag_color = vec4(c * mix(0.75, 1.0, max(dot(n, v), 0.0)), 1.0);
    return;
  }
  if (params.x < 0.5) {  // "Surfaces": flat colour
    frag_color = vec4(color.rgb, 1.0);
    return;
  }
  // "Shaded": Blinn-Phong with two headlights (view space), back faces darker.
  vec3 key = normalize(vec3(0.35, 0.45, 1.0));
  vec3 fill = normalize(vec3(-0.6, -0.3, 0.5));
  float diffuse = 0.22 + 0.62 * max(dot(n, key), 0.0) + 0.22 * max(dot(n, fill), 0.0);
  float spec = 0.28 * pow(max(dot(n, normalize(key + v)), 0.0), 48.0);
  frag_color = vec4((color.rgb * diffuse + vec3(spec)) * side, 1.0);
}
