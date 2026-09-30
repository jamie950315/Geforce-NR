#pragma once

// Compare every captured channel, including the native FP16 HDR source.
// A gray thumbnail or checksum cannot establish complete image equality.
static const char kGfnStaticCompareHlsl[] = R"hlsl(
Texture2D<float4> currentFrame : register(t0);
Texture2D<float4> previousFrame : register(t1);
RWBuffer<uint> changed : register(u0);
cbuffer Bounds : register(b0) { uint width; uint height; };
groupshared uint groupChanged;
[numthreads(8,8,1)]
void CSMain(uint3 p : SV_DispatchThreadID, uint lane : SV_GroupIndex) {
    if (lane == 0) groupChanged = 0;
    GroupMemoryBarrierWithGroupSync();
    if (p.x < width && p.y < height) {
        float4 a = currentFrame.Load(int3(p.xy,0));
        float4 b = previousFrame.Load(int3(p.xy,0));
        // NaN is always a change. No tolerance hides small HDR/color edits.
        if (any(a != b)) InterlockedOr(groupChanged,1);
    }
    GroupMemoryBarrierWithGroupSync();
    if (lane == 0 && groupChanged != 0) InterlockedOr(changed[0],1);
}
)hlsl";

class GfnStaticFramePolicy {
    bool rendered_ = false;
public:
    void clear() { rendered_ = false; }
    // CAP1 may capture several surfaces without evaluating any of them.
    // Equality with an unrendered capture must never reuse an older output.
    bool capture(bool changed) {
        const bool repeat = rendered_ && !changed;
        if (changed) rendered_ = false;
        return repeat;
    }
    void rendered() { rendered_ = true; }
};
