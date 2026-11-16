// Convert a tile-row-aligned region of a PICA render target to upright LCD pixels.
[[vk::combinedImageSampler]] Texture2D<float4> Source : register(t0, space2);
[[vk::combinedImageSampler]] SamplerState Filter : register(s0, space2);

cbuffer Blit : register(b0, space3) {
    float4 Size;
    int4 Mode;
};

float4 main(float4 position : SV_Position) : SV_Target0 {
    int x = int(Size.y) - 1 - int(position.y);
    int y = Mode.x != 0 ? int(Size.x) - 1 - int(position.x) : int(position.x);
    float2 block = float2(1 << Mode.y, 1 << Mode.z);
    float2 texel = float2(x, y) * block + block * 0.5 + float2(0, Mode.w);
    return float4(Source.SampleLevel(Filter, texel / Size.zw, 0).rgb, 1.0);
}
