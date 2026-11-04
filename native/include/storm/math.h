// Portable math used by the runtime packages, the fighter simulation and the
// GLES renderer.  Matrices are column-major and match glTF / the Python packer.
#pragma once

#include <cmath>
#include <cstddef>

namespace storm {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kDeg2Rad = kPi / 180.0f;

inline float clampf(float value, float low, float high) {
    return value < low ? low : (value > high ? high : value);
}

inline float lerpf(float a, float b, float t) { return a + (b - a) * t; }

struct Vec2 {
    float x = 0.0f;
    float y = 0.0f;
    Vec2() = default;
    Vec2(float px, float py) : x(px), y(py) {}
};

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    Vec3() = default;
    Vec3(float px, float py, float pz) : x(px), y(py), z(pz) {}

    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
    Vec3 operator-() const { return {-x, -y, -z}; }
    Vec3& operator+=(const Vec3& o) { x += o.x; y += o.y; z += o.z; return *this; }
    Vec3& operator-=(const Vec3& o) { x -= o.x; y -= o.y; z -= o.z; return *this; }

    float dot(const Vec3& o) const { return x * o.x + y * o.y + z * o.z; }
    Vec3 cross(const Vec3& o) const {
        return {y * o.z - z * o.y, z * o.x - x * o.z, x * o.y - y * o.x};
    }
    float lengthSquared() const { return x * x + y * y + z * z; }
    float length() const { return std::sqrt(lengthSquared()); }
    Vec3 normalized() const {
        const float len = length();
        return len > 1e-6f ? Vec3{x / len, y / len, z / len} : Vec3{0.0f, 0.0f, 0.0f};
    }
    Vec3 withY(float value) const { return {x, value, z}; }
};

inline Vec3 lerp(const Vec3& a, const Vec3& b, float t) {
    return {lerpf(a.x, b.x, t), lerpf(a.y, b.y, t), lerpf(a.z, b.z, t)};
}

struct Vec4 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 1.0f;
    Vec4() = default;
    Vec4(float px, float py, float pz, float pw) : x(px), y(py), z(pz), w(pw) {}
};

struct Quat {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 1.0f;
    Quat() = default;
    Quat(float qx, float qy, float qz, float qw) : x(qx), y(qy), z(qz), w(qw) {}

    static Quat identity() { return {}; }

    static Quat fromAxisAngle(const Vec3& axis, float radians) {
        const Vec3 n = axis.normalized();
        const float half = radians * 0.5f;
        const float s = std::sin(half);
        return {n.x * s, n.y * s, n.z * s, std::cos(half)};
    }

    static Quat fromEulerY(float radians) {
        const float half = radians * 0.5f;
        return {0.0f, std::sin(half), 0.0f, std::cos(half)};
    }

    Quat operator*(const Quat& o) const {
        return {
            w * o.x + x * o.w + y * o.z - z * o.y,
            w * o.y - x * o.z + y * o.w + z * o.x,
            w * o.z + x * o.y - y * o.x + z * o.w,
            w * o.w - x * o.x - y * o.y - z * o.z,
        };
    }

    float length() const { return std::sqrt(x * x + y * y + z * z + w * w); }

    Quat normalized() const {
        const float len = length();
        if (len < 1e-8f) return identity();
        return {x / len, y / len, z / len, w / len};
    }

    Vec3 rotate(const Vec3& v) const {
        const Vec3 u{x, y, z};
        const Vec3 t = u.cross(v) * 2.0f;
        return v + t * w + u.cross(t);
    }
};

inline Quat slerp(const Quat& a, const Quat& b, float t) {
    Quat target = b;
    float dot = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w;
    if (dot < 0.0f) {
        target = {-b.x, -b.y, -b.z, -b.w};
        dot = -dot;
    }
    if (dot > 0.9995f) {
        return Quat{a.x + (target.x - a.x) * t, a.y + (target.y - a.y) * t,
                    a.z + (target.z - a.z) * t, a.w + (target.w - a.w) * t}.normalized();
    }
    const float theta = std::acos(clampf(dot, -1.0f, 1.0f));
    const float sinTheta = std::sin(theta);
    const float wa = std::sin((1.0f - t) * theta) / sinTheta;
    const float wb = std::sin(t * theta) / sinTheta;
    return Quat{a.x * wa + target.x * wb, a.y * wa + target.y * wb,
                a.z * wa + target.z * wb, a.w * wa + target.w * wb}.normalized();
}

struct Mat4 {
    float m[16] = {1.0f, 0.0f, 0.0f, 0.0f,
                   0.0f, 1.0f, 0.0f, 0.0f,
                   0.0f, 0.0f, 1.0f, 0.0f,
                   0.0f, 0.0f, 0.0f, 1.0f};

    static Mat4 identity() { return {}; }

    static Mat4 translation(const Vec3& t) {
        Mat4 r;
        r.m[12] = t.x;
        r.m[13] = t.y;
        r.m[14] = t.z;
        return r;
    }

    static Mat4 scale(float s) {
        Mat4 r;
        r.m[0] = s;
        r.m[5] = s;
        r.m[10] = s;
        return r;
    }

    Mat4 operator*(const Mat4& o) const {
        Mat4 r;
        for (int column = 0; column < 4; ++column) {
            for (int row = 0; row < 4; ++row) {
                float sum = 0.0f;
                for (int k = 0; k < 4; ++k) {
                    sum += m[k * 4 + row] * o.m[column * 4 + k];
                }
                r.m[column * 4 + row] = sum;
            }
        }
        return r;
    }

    Vec3 transformPoint(const Vec3& p) const {
        return {
            m[0] * p.x + m[4] * p.y + m[8] * p.z + m[12],
            m[1] * p.x + m[5] * p.y + m[9] * p.z + m[13],
            m[2] * p.x + m[6] * p.y + m[10] * p.z + m[14],
        };
    }

    Vec3 transformDirection(const Vec3& d) const {
        return {
            m[0] * d.x + m[4] * d.y + m[8] * d.z,
            m[1] * d.x + m[5] * d.y + m[9] * d.z,
            m[2] * d.x + m[6] * d.y + m[10] * d.z,
        };
    }

    Vec3 translationPart() const { return {m[12], m[13], m[14]}; }
};

inline Mat4 makeTrs(const Vec3& translation, const Quat& rotation, float scale = 1.0f) {
    const float x = rotation.x, y = rotation.y, z = rotation.z, w = rotation.w;
    const float xx = x * x, yy = y * y, zz = z * z;
    const float xy = x * y, xz = x * z, yz = y * z;
    const float wx = w * x, wy = w * y, wz = w * z;
    Mat4 r;
    r.m[0] = (1.0f - 2.0f * (yy + zz)) * scale;
    r.m[1] = (2.0f * (xy + wz)) * scale;
    r.m[2] = (2.0f * (xz - wy)) * scale;
    r.m[3] = 0.0f;
    r.m[4] = (2.0f * (xy - wz)) * scale;
    r.m[5] = (1.0f - 2.0f * (xx + zz)) * scale;
    r.m[6] = (2.0f * (yz + wx)) * scale;
    r.m[7] = 0.0f;
    r.m[8] = (2.0f * (xz + wy)) * scale;
    r.m[9] = (2.0f * (yz - wx)) * scale;
    r.m[10] = (1.0f - 2.0f * (xx + yy)) * scale;
    r.m[11] = 0.0f;
    r.m[12] = translation.x;
    r.m[13] = translation.y;
    r.m[14] = translation.z;
    r.m[15] = 1.0f;
    return r;
}

inline Mat4 perspective(float fovYRadians, float aspect, float nearPlane, float farPlane) {
    const float f = 1.0f / std::tan(fovYRadians * 0.5f);
    Mat4 r;
    for (float& value : r.m) value = 0.0f;
    r.m[0] = f / (aspect > 1e-4f ? aspect : 1.0f);
    r.m[5] = f;
    r.m[10] = (farPlane + nearPlane) / (nearPlane - farPlane);
    r.m[11] = -1.0f;
    r.m[14] = (2.0f * farPlane * nearPlane) / (nearPlane - farPlane);
    return r;
}

inline Mat4 lookAt(const Vec3& eye, const Vec3& target, const Vec3& up) {
    const Vec3 forward = (target - eye).normalized();
    const Vec3 side = forward.cross(up).normalized();
    const Vec3 trueUp = side.cross(forward);
    Mat4 r;
    r.m[0] = side.x;      r.m[4] = side.y;      r.m[8] = side.z;       r.m[12] = -side.dot(eye);
    r.m[1] = trueUp.x;    r.m[5] = trueUp.y;    r.m[9] = trueUp.z;     r.m[13] = -trueUp.dot(eye);
    r.m[2] = -forward.x;  r.m[6] = -forward.y;  r.m[10] = -forward.z;  r.m[14] = forward.dot(eye);
    r.m[3] = 0.0f;        r.m[7] = 0.0f;        r.m[11] = 0.0f;        r.m[15] = 1.0f;
    return r;
}

}  // namespace storm
