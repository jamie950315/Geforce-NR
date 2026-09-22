// Opt-in, bounded proof capture for live WGC + NVOFA + HUD Guard.
// The source, pre-HUD output, and post-HUD output copies are recorded into the
// same command list as the evaluated frame. GFN_LIVE_PAIR_DIR must name an
// existing directory and GFN_LIVE_PAIR_FRAMES must contain exactly three
// distinct decimal frame indexes (for example: 30,60,90).
#include <cerrno>
#include <cstdlib>
#include <string>

struct LivePairProbeState {
    bool inspected = false, enabled = false, failed = false;
    bool nvofa = false, selected = false;
    UINT width = 0, height = 0, rows = 0;
    UINT64 row_bytes = 0, total_bytes = 0;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint = {};
    ID3D12Resource *readback[3] = {};
    uint32_t wanted[3] = {};
    bool captured[3] = {};
    uint32_t frame_index = 0;
    int64_t pts = 0;
    UINT64 capture_serial = 0, source_qpc = 0;
    uintptr_t hwnd = 0;
    wchar_t directory[32768] = {};
};
static LivePairProbeState g_live_pair;

template<class T> static void LivePairRelease(T *&p) {
    if (p) { p->Release(); p = nullptr; }
}

static bool LivePairError(const char *reason) {
    Log("[live-pair] ERROR %s", reason);
    g_live_pair.failed = true;
    return false;
}

static bool LivePairParseFrames(const char *text, uint32_t out[3]) {
    if (!text || !*text) return false;
    const char *p = text;
    for (int i = 0; i < 3; ++i) {
        if (*p < '0' || *p > '9') return false;
        errno = 0;
        char *end = nullptr;
        const unsigned long value = strtoul(p, &end, 10);
        if (errno == ERANGE || end == p || value > UINT32_MAX) return false;
        out[i] = static_cast<uint32_t>(value);
        if (i < 2) {
            if (*end != ',') return false;
            p = end + 1;
        } else if (*end != '\0') return false;
    }
    return out[0] != out[1] && out[0] != out[2] && out[1] != out[2];
}

static bool LivePairInspect() {
    if (g_live_pair.inspected) return !g_live_pair.failed;
    g_live_pair.inspected = true;
    const DWORD n = GetEnvironmentVariableW(
        L"GFN_LIVE_PAIR_DIR", g_live_pair.directory, _countof(g_live_pair.directory));
    if (!n) { Log("[live-pair] disabled"); return true; }
    if (n >= _countof(g_live_pair.directory)) return LivePairError("output path too long");
    const DWORD attrs = GetFileAttributesW(g_live_pair.directory);
    if (attrs == INVALID_FILE_ATTRIBUTES || !(attrs & FILE_ATTRIBUTE_DIRECTORY))
        return LivePairError("output directory must already exist");
    char frames[128] = {};
    const DWORD f = GetEnvironmentVariableA("GFN_LIVE_PAIR_FRAMES", frames, sizeof(frames));
    if (!f) strcpy_s(frames, "30,60,90");
    if (f >= sizeof(frames) || !LivePairParseFrames(frames, g_live_pair.wanted))
        return LivePairError("GFN_LIVE_PAIR_FRAMES must be three distinct decimal indexes");
    g_live_pair.enabled = true;
    Log("[live-pair] armed frames=%u,%u,%u", g_live_pair.wanted[0],
        g_live_pair.wanted[1], g_live_pair.wanted[2]);
    return true;
}

static void LivePairResetFrame() {
    g_live_pair.nvofa = false;
    g_live_pair.selected = false;
}

static void LivePairSetNvofa(bool used) { g_live_pair.nvofa = used; }

static bool LivePairSelect(uint32_t index, int64_t pts, bool source_fresh) {
    if (!LivePairInspect()) return false;
    if (!g_live_pair.enabled) return true;
    int target = -1;
    for (int i = 0; i < 3; ++i)
        if (!g_live_pair.captured[i] && g_live_pair.wanted[i] == index) target = i;
    if (target < 0) return true;
    if (!g_wgc_active || !source_fresh || !g_live_pair.nvofa || !g_hud.enabled)
        return LivePairError("target frame lacks fresh WGC, NVOFA, or HUD Guard");
    if (strcmp(g_frame_stamp.kind, "wgc") != 0 || !g_frame_stamp.capture ||
        !g_frame_stamp.source_qpc)
        return LivePairError("target frame lacks WGC capture identity");
    g_live_pair.selected = true;
    g_live_pair.frame_index = index;
    g_live_pair.pts = pts;
    g_live_pair.capture_serial = g_frame_stamp.capture;
    g_live_pair.source_qpc = g_frame_stamp.source_qpc;
    g_live_pair.hwnd = reinterpret_cast<uintptr_t>(g_wgc_hwnd);
    return true;
}

static bool LivePairEnsureResources(VideoState &v) {
    const UINT width = v.upscale ? v.full_w : v.w;
    const UINT height = v.upscale ? v.full_h : v.hgt;
    if (g_live_pair.readback[0])
        return width == g_live_pair.width && height == g_live_pair.height
            ? true : LivePairError("capture geometry changed");
    const D3D12_RESOURCE_DESC source = v.color.tex->GetDesc();
    const D3D12_RESOURCE_DESC output = v.output->GetDesc();
    if (source.Format != DXGI_FORMAT_R8G8B8A8_UNORM ||
        output.Format != DXGI_FORMAT_R8G8B8A8_UNORM ||
        source.Width != width || source.Height != height ||
        output.Width != width || output.Height != height)
        return LivePairError("probe requires matching SDR RGBA8 textures");
    D3D12_RESOURCE_DESC texture = output;
    h.dev->GetCopyableFootprints(&texture, 0, 1, 0, &g_live_pair.footprint,
        &g_live_pair.rows, &g_live_pair.row_bytes, &g_live_pair.total_bytes);
    if (g_live_pair.rows != height || g_live_pair.row_bytes < UINT64(width) * 4)
        return LivePairError("unexpected copy footprint");
    D3D12_HEAP_PROPERTIES heap = {}; heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC buffer = {};
    buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width = g_live_pair.total_bytes; buffer.Height = 1;
    buffer.DepthOrArraySize = 1; buffer.MipLevels = 1;
    buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    for (auto &resource : g_live_pair.readback) {
        if (FAILED(h.dev->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&resource))))
            return LivePairError("readback allocation failed");
    }
    g_live_pair.width = width; g_live_pair.height = height;
    return true;
}

static void LivePairCopy(ID3D12Resource *texture, ID3D12Resource *readback,
                         D3D12_RESOURCE_STATES before) {
    auto to_copy = Transition(texture, before, D3D12_RESOURCE_STATE_COPY_SOURCE);
    h.list->ResourceBarrier(1, &to_copy);
    D3D12_TEXTURE_COPY_LOCATION src = {}, dst = {};
    src.pResource = texture; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.pResource = readback; dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = g_live_pair.footprint;
    h.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    auto restore = Transition(texture, D3D12_RESOURCE_STATE_COPY_SOURCE, before);
    h.list->ResourceBarrier(1, &restore);
}

static bool LivePairBegin(VideoState &v, bool &sampled) {
    sampled = false;
    if (!g_live_pair.selected) return !g_live_pair.failed;
    if (!LivePairEnsureResources(v)) return false;
    LivePairCopy(v.color.tex, g_live_pair.readback[0],
                 D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    LivePairCopy(v.output, g_live_pair.readback[1], D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    sampled = true;
    return true;
}

static bool LivePairEnd(VideoState &v, bool sampled) {
    if (!sampled) return !g_live_pair.failed;
    LivePairCopy(v.output, g_live_pair.readback[2], D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    return true;
}

static bool LivePairWriteRaw(const wchar_t *stage, ID3D12Resource *resource,
                             std::wstring &name) {
    wchar_t leaf[96] = {};
    swprintf_s(leaf, L"pair-%010u-%s.rgba", g_live_pair.frame_index, stage);
    name = leaf;
    std::wstring path = std::wstring(g_live_pair.directory) + L"\\" + leaf;
    if (GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES)
        return LivePairError("refusing to overwrite existing probe output");
    FILE *file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"wb") != 0 || !file)
        return LivePairError("raw output open failed");
    BYTE *data = nullptr;
    D3D12_RANGE read = {0, static_cast<SIZE_T>(g_live_pair.total_bytes)};
    if (FAILED(resource->Map(0, &read, reinterpret_cast<void **>(&data)))) {
        fclose(file); return LivePairError("readback map failed");
    }
    bool ok = true;
    const size_t packed = size_t(g_live_pair.width) * 4;
    for (UINT y = 0; y < g_live_pair.height; ++y)
        ok &= fwrite(data + g_live_pair.footprint.Offset +
                     size_t(y) * g_live_pair.footprint.Footprint.RowPitch,
                     1, packed, file) == packed;
    D3D12_RANGE none = {0, 0}; resource->Unmap(0, &none);
    ok &= fclose(file) == 0;
    return ok ? true : LivePairError("raw output write failed");
}

static bool LivePairCommit(bool sampled, UINT64 fence) {
    if (!sampled) return !g_live_pair.failed;
    if (!fence || !WaitFenceValue(h.fence, fence, 60000, "live-pair", false))
        return LivePairError("copy fence failed");
    std::wstring names[3];
    if (!LivePairWriteRaw(L"source", g_live_pair.readback[0], names[0]) ||
        !LivePairWriteRaw(L"pre-hud", g_live_pair.readback[1], names[1]) ||
        !LivePairWriteRaw(L"post-hud", g_live_pair.readback[2], names[2])) return false;
    wchar_t leaf[96] = {};
    swprintf_s(leaf, L"pair-%010u.json", g_live_pair.frame_index);
    const std::wstring path = std::wstring(g_live_pair.directory) + L"\\" + leaf;
    if (GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES)
        return LivePairError("refusing to overwrite existing probe metadata");
    FILE *file = nullptr;
    if (_wfopen_s(&file, path.c_str(), L"wb") != 0 || !file)
        return LivePairError("metadata output open failed");
    const int written = fprintf(file,
        "{\"schema\":1,\"frame_index\":%u,\"pts\":%lld,\"width\":%u,\"height\":%u,"
        "\"capture_kind\":\"wgc\",\"capture_serial\":%llu,\"source_qpc\":%llu,"
        "\"hwnd\":%llu,\"source_fresh\":true,\"nvofa_used\":true,\"hud_guard\":true,"
        "\"same_command_list\":true,\"copy_submission_fence\":%llu,"
        "\"source\":\"%ls\",\"pre_hud\":\"%ls\",\"post_hud\":\"%ls\"}\n",
        g_live_pair.frame_index, static_cast<long long>(g_live_pair.pts),
        g_live_pair.width, g_live_pair.height,
        static_cast<unsigned long long>(g_live_pair.capture_serial),
        static_cast<unsigned long long>(g_live_pair.source_qpc),
        static_cast<unsigned long long>(g_live_pair.hwnd),
        static_cast<unsigned long long>(fence), names[0].c_str(), names[1].c_str(), names[2].c_str());
    const int close_result = fclose(file);
    const bool ok = written > 0 && close_result == 0;
    if (!ok) return LivePairError("metadata output write failed");
    for (int i = 0; i < 3; ++i)
        if (g_live_pair.wanted[i] == g_live_pair.frame_index) g_live_pair.captured[i] = true;
    g_live_pair.selected = false;
    Log("[live-pair] captured frame=%u capture=%llu source_qpc=%llu fence=%llu",
        g_live_pair.frame_index,
        static_cast<unsigned long long>(g_live_pair.capture_serial),
        static_cast<unsigned long long>(g_live_pair.source_qpc),
        static_cast<unsigned long long>(fence));
    return true;
}

static void CloseLivePair() {
    if (g_live_pair.enabled) {
        const unsigned count = unsigned(g_live_pair.captured[0]) +
            unsigned(g_live_pair.captured[1]) + unsigned(g_live_pair.captured[2]);
        Log("[live-pair] complete samples=%u/3", count);
    }
    for (auto &resource : g_live_pair.readback) LivePairRelease(resource);
    g_live_pair.enabled = false;
}
