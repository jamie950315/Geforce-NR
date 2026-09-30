// Included after capture globals, before CloseCaptureBridge/SwizzleCapture.
#include "static_compare.h"

static ID3D12RootSignature *g_static_rs = nullptr;
static ID3D12PipelineState *g_static_pso = nullptr;
static ID3D12DescriptorHeap *g_static_heap = nullptr;
static ID3D12Resource *g_static_previous = nullptr;
static ID3D12Resource *g_static_flag = nullptr;
static ID3D12Resource *g_static_readback = nullptr;
static ID3D12Resource *g_static_zero = nullptr;
static bool g_static_have_source = false;
static bool g_static_equal = false;
static float g_static_white = 0;
static GfnStaticFramePolicy g_static_policy;

static void CloseStaticCapture()
{
    g_static_equal = g_static_have_source = false;
    g_static_policy.clear();
    g_static_white = 0;
    if (g_static_previous) { g_static_previous->Release(); g_static_previous = nullptr; }
    if (g_static_flag) { g_static_flag->Release(); g_static_flag = nullptr; }
    if (g_static_readback) { g_static_readback->Release(); g_static_readback = nullptr; }
    if (g_static_zero) { g_static_zero->Release(); g_static_zero = nullptr; }
    if (g_static_heap) { g_static_heap->Release(); g_static_heap = nullptr; }
    if (g_static_pso) { g_static_pso->Release(); g_static_pso = nullptr; }
    if (g_static_rs) { g_static_rs->Release(); g_static_rs = nullptr; }
}

static bool EnsureStaticCapture(ID3D12Resource *source)
{
    if (g_static_previous) return true;
    auto td = source->GetDesc();
    if (td.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || td.MipLevels != 1 ||
        td.DepthOrArraySize != 1 || td.Width > 7680 || td.Height > 4320)
        return FailGpuWork("static-capture", "source-bounds", E_FAIL);
    ID3DBlob *code = nullptr, *error = nullptr, *signature = nullptr;
    HRESULT hr = D3DCompile(kGfnStaticCompareHlsl, sizeof(kGfnStaticCompareHlsl)-1,
        "static-compare.hlsl", nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &code, &error);
    if (FAILED(hr)) {
        Log("[static] compile failed: %s", error ? (char*)error->GetBufferPointer() : "?");
        if (error) error->Release();
        return FailGpuWork("static-capture", "shader-compile", hr);
    }
    if (error) { error->Release(); error = nullptr; }
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 2;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 1;
    D3D12_ROOT_PARAMETER parameters[3] = {};
    for (UINT i=0; i<2; ++i) {
        parameters[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[i].DescriptorTable.NumDescriptorRanges = 1;
        parameters[i].DescriptorTable.pDescriptorRanges = &ranges[i];
    }
    parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    parameters[2].Constants.Num32BitValues = 2;
    D3D12_ROOT_SIGNATURE_DESC rd = {};
    rd.NumParameters = 3; rd.pParameters = parameters;
    hr = D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,&signature,&error);
    if (error) error->Release();
    if (SUCCEEDED(hr)) hr = h.dev->CreateRootSignature(0,signature->GetBufferPointer(),
        signature->GetBufferSize(),__uuidof(ID3D12RootSignature),(void**)&g_static_rs);
    if (signature) signature->Release();
    if (SUCCEEDED(hr)) {
        D3D12_COMPUTE_PIPELINE_STATE_DESC pd = {};
        pd.pRootSignature = g_static_rs;
        pd.CS = {code->GetBufferPointer(),code->GetBufferSize()};
        hr = h.dev->CreateComputePipelineState(&pd,__uuidof(ID3D12PipelineState),(void**)&g_static_pso);
    }
    code->Release();
    if (FAILED(hr)) return FailGpuWork("static-capture", "pipeline-create", hr);
    D3D12_DESCRIPTOR_HEAP_DESC hd = {};
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    hd.NumDescriptors = 3; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    hr = h.dev->CreateDescriptorHeap(&hd,__uuidof(ID3D12DescriptorHeap),(void**)&g_static_heap);
    if (FAILED(hr)) return FailGpuWork("static-capture", "heap-create", hr);
    td.Flags = D3D12_RESOURCE_FLAG_NONE;
    D3D12_HEAP_PROPERTIES hp = {}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
    hr = h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&td,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,
        __uuidof(ID3D12Resource),(void**)&g_static_previous);
    if (FAILED(hr)) return FailGpuWork("static-capture", "history-create", hr);
    D3D12_RESOURCE_DESC bd = {};
    bd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; bd.Width = 4; bd.Height = 1;
    bd.DepthOrArraySize = bd.MipLevels = 1; bd.SampleDesc.Count = 1;
    bd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; bd.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    hr = h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&bd,
        D3D12_RESOURCE_STATE_COPY_SOURCE,nullptr,__uuidof(ID3D12Resource),(void**)&g_static_flag);
    bd.Flags = D3D12_RESOURCE_FLAG_NONE; hp.Type = D3D12_HEAP_TYPE_READBACK;
    if (SUCCEEDED(hr)) hr = h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&bd,
        D3D12_RESOURCE_STATE_COPY_DEST,nullptr,__uuidof(ID3D12Resource),(void**)&g_static_readback);
    hp.Type = D3D12_HEAP_TYPE_UPLOAD;
    if (SUCCEEDED(hr)) hr = h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&bd,
        D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,__uuidof(ID3D12Resource),(void**)&g_static_zero);
    if (FAILED(hr)) return FailGpuWork("static-capture", "flag-create", hr);
    void *mapped = nullptr; D3D12_RANGE none = {0,0};
    hr = g_static_zero->Map(0,&none,&mapped);
    if (FAILED(hr)) return FailGpuWork("static-capture", "zero-map", hr);
    memset(mapped,0,4); g_static_zero->Unmap(0,nullptr);
    Log("[static] exact full-source comparison active; FP16 HDR included");
    return true;
}

// Source is SRV here. Dedicated descriptors are retired at the existing
// swizzle/gray fence, along with the four-byte flag and source-history copy.
static bool RecordStaticCapture(ID3D12Resource *source)
{
    if (!EnsureStaticCapture(source)) return false;
    const UINT stride = h.dev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    auto cpu = g_static_heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC sd = {};
    sd.Format = source->GetDesc().Format; sd.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    sd.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; sd.Texture2D.MipLevels = 1;
    h.dev->CreateShaderResourceView(source,&sd,cpu); cpu.ptr += stride;
    h.dev->CreateShaderResourceView(g_static_previous,&sd,cpu); cpu.ptr += stride;
    D3D12_UNORDERED_ACCESS_VIEW_DESC ud = {};
    ud.Format = DXGI_FORMAT_R32_UINT; ud.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    ud.Buffer.NumElements = 1;
    h.dev->CreateUnorderedAccessView(g_static_flag,nullptr,&ud,cpu);
    auto to_copy = Transition(g_static_flag,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
    h.list->ResourceBarrier(1,&to_copy);
    h.list->CopyBufferRegion(g_static_flag,0,g_static_zero,0,4);
    auto to_uav = Transition(g_static_flag,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    h.list->ResourceBarrier(1,&to_uav);
    ID3D12DescriptorHeap *heaps[] = {g_static_heap}; h.list->SetDescriptorHeaps(1,heaps);
    h.list->SetComputeRootSignature(g_static_rs); h.list->SetPipelineState(g_static_pso);
    auto gpu = g_static_heap->GetGPUDescriptorHandleForHeapStart();
    h.list->SetComputeRootDescriptorTable(0,gpu); gpu.ptr += 2*stride;
    h.list->SetComputeRootDescriptorTable(1,gpu);
    UINT sizes[2] = {(UINT)source->GetDesc().Width,source->GetDesc().Height};
    h.list->SetComputeRoot32BitConstants(2,2,sizes,0);
    h.list->Dispatch((sizes[0]+7)/8,(sizes[1]+7)/8,1);
    D3D12_RESOURCE_BARRIER barriers[] = {
        Transition(g_static_flag,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE),
        Transition(g_static_previous,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST),
        Transition(source,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE)};
    h.list->ResourceBarrier(3,barriers);
    h.list->CopyBufferRegion(g_static_readback,0,g_static_flag,0,4);
    h.list->CopyResource(g_static_previous,source);
    D3D12_RESOURCE_BARRIER back[] = {
        Transition(g_static_previous,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),
        Transition(source,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
    h.list->ResourceBarrier(2,back);
    return true;
}

static bool ReadStaticCapture()
{
    UINT *mapped = nullptr; D3D12_RANGE range = {0,4};
    const HRESULT hr = g_static_readback->Map(0,&range,(void**)&mapped);
    if (FAILED(hr)) return FailGpuWork("static-capture", "flag-map", hr);
    const bool changed = *mapped != 0 || !g_static_have_source || g_static_white != g_hdr_frame_white;
    D3D12_RANGE none = {0,0}; g_static_readback->Unmap(0,&none);
    g_static_equal = g_static_policy.capture(changed);
    g_static_have_source = true; g_static_white = g_hdr_frame_white;
    return true;
}
