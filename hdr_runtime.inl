// Isolated HDR status and opt-in, same-frame numeric proof. Not a recording path.
#include <cmath>
#include <bcrypt.h>
#pragma comment(lib, "bcrypt.lib")
#ifndef GFN_HDR_MAPPING
#define GFN_HDR_MAPPING "legacy"
#endif

static bool GfnHdrHashRows(const BYTE *pixels, const D3D12_PLACED_SUBRESOURCE_FOOTPRINT &fp,
                          UINT rows, UINT64 rowbytes, char output[65]) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    BYTE digest[32] = {};
    bool good = BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0) >= 0;
    if (good) good = BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0) >= 0;
    for (UINT row=0; row<rows && good; ++row)
        good = BCryptHashData(hash,const_cast<BYTE *>(pixels+fp.Offset+size_t(row)*fp.Footprint.RowPitch),ULONG(rowbytes),0) >= 0;
    if (good) good = BCryptFinishHash(hash,digest,sizeof(digest),0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm,0);
    if (good) for (unsigned i=0;i<32;++i) sprintf_s(output+i*2,65-i*2,"%02x",unsigned(digest[i]));
    return good;
}

static int GfnHdrDisplayCommand(const char *text) {
    char *end = nullptr;
    const auto id = _strtoui64(text, &end, 10);
    if (!text[0] || !end || *end) return 2;
    HWND window = reinterpret_cast<HWND>(static_cast<uintptr_t>(id));
    if (window && !IsWindow(window)) return 2;
    const auto display = QueryHdrDisplay(MonitorFromWindow(window, MONITOR_DEFAULTTOPRIMARY));
    printf("{\"known\":%s,\"enabled\":%s,\"white\":%.9g}\n",
        display.known ? "true" : "false", display.enabled ? "true" : "false", display.white);
    return display.known ? 0 : 3;
}

static bool GfnHdrStatus(UINT w, UINT height) {
    static bool written = false;
    if (written) return true;
    wchar_t path[32768] = {};
    const DWORD len = GetEnvironmentVariableW(L"GFN_HDR_STATUS", path, _countof(path));
    if (!len) return true;
    if (len >= _countof(path)-8) return false;
    const std::wstring temporary = std::wstring(path) + L".tmp";
    FILE *file = nullptr;
    if (_wfopen_s(&file, temporary.c_str(), L"wb") || !file) return false;
    const int count = fprintf(file, "{\"active\":true,\"mapping\":\"" GFN_HDR_MAPPING "\",\"capture\":\"rgba16f\","
        "\"output\":\"rgba16f\",\"color_space\":\"scRGB-linear-BT709\","
        "\"neural_input\":\"SDR-proxy\",\"white\":%.9g,\"width\":%u,\"height\":%u}",
        g_hdr_frame_white, w, height);
    const bool good = count > 0 && !ferror(file);
    const int closed = fclose(file);
    if (!good || closed || !MoveFileExW(temporary.c_str(), path, MOVEFILE_REPLACE_EXISTING)) return false;
    written = true;
    Log("[hdr] active: FP16 capture -> SDR neural proxy -> FP16 scRGB residual output");
    return true;
}

static bool GfnHdrProof(VideoState &v, bool bypass) {
    static unsigned frames = 0;
    static bool completed = false;
    if (completed) return true;
    wchar_t folder[32768] = {};
    const DWORD len = GetEnvironmentVariableW(L"GFN_HDR_PROOF_DIR", folder, _countof(folder));
    if (!len) { completed = true; return true; }
    if (len >= _countof(folder)-64) return false;
    if (++frames != 30) return true;
    char manifest_hash[65] = {};
    if (GetEnvironmentVariableA("GFN_HDR_MANIFEST_SHA256",manifest_hash,sizeof(manifest_hash)) != 64)
        return false;
    for (unsigned i=0;i<64;++i)
        if (!((manifest_hash[i]>='0' && manifest_hash[i]<='9') || (manifest_hash[i]>='a' && manifest_hash[i]<='f'))) return false;
    DWORD target_pid = 0;
    if (!g_wgc_active || !GetWindowThreadProcessId(g_wgc_hwnd,&target_pid) ||
        !g_capture_generation || !g_frame_stamp.capture || !g_frame_stamp.source_qpc) return false;
    ID3D12Resource *textures[] = {g_dda_d12, g_hdr_output, v.color.tex, bypass ? v.color.tex : v.output};
    const D3D12_RESOURCE_STATES states[] = {D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COMMON,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
        bypass ? D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE : D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
    const wchar_t *names[] = {L"source.fp16", L"output.fp16", L"proxy-in.rgba", L"proxy-out.rgba"};
    winrt::com_ptr<ID3D12Resource> readbacks[4];
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprints[4] = {};
    UINT rows[4] = {};
    UINT64 rowbytes[4] = {}, sizes[4] = {};
    char hashes[4][65] = {};
    for (unsigned i=0; i<4; ++i) {
        const auto desc = textures[i]->GetDesc();
        h.dev->GetCopyableFootprints(&desc,0,1,0,&footprints[i],&rows[i],&rowbytes[i],&sizes[i]);
        D3D12_HEAP_PROPERTIES hp = {}; hp.Type = D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC rd = {}; rd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        rd.Width = sizes[i]; rd.Height = 1; rd.DepthOrArraySize = rd.MipLevels = 1;
        rd.SampleDesc.Count = 1; rd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&rd,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(readbacks[i].put())))) return false;
    }
    if (!BeginCommands()) return false;
    for (unsigned i=0; i<4; ++i) {
        auto pre = Transition(textures[i],states[i],D3D12_RESOURCE_STATE_COPY_SOURCE);
        h.list->ResourceBarrier(1,&pre);
        D3D12_TEXTURE_COPY_LOCATION src = {}, dst = {};
        src.pResource = textures[i]; src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource = readbacks[i].get(); dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint = footprints[i];
        h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        auto post = Transition(textures[i],D3D12_RESOURCE_STATE_COPY_SOURCE,states[i]);
        h.list->ResourceBarrier(1,&post);
    }
    const auto fence = EndCommands();
    if (!WaitFenceValue(h.fence,fence,10000,"hdr-proof")) {
        // Submitted GPU resources must outlive a failed fence wait.
        for (auto &resource : readbacks) resource.detach();
        return false;
    }
    for (unsigned i=0; i<4; ++i) {
        BYTE *pixels = nullptr;
        D3D12_RANGE range = {0,static_cast<SIZE_T>(sizes[i])};
        if (FAILED(readbacks[i]->Map(0,&range,reinterpret_cast<void **>(&pixels)))) return false;
        FILE *file = nullptr;
        const std::wstring path = std::wstring(folder)+L"\\"+names[i];
        bool good = !_wfopen_s(&file,path.c_str(),L"wb") && file;
        if (good) {
            for (UINT row=0; row<rows[i] && good; ++row)
                good = fwrite(pixels+footprints[i].Offset+size_t(row)*footprints[i].Footprint.RowPitch,
                              1,size_t(rowbytes[i]),file) == rowbytes[i];
            if (fclose(file)) good = false;
        }
        if (good) good = GfnHdrHashRows(pixels,footprints[i],rows[i],rowbytes[i],hashes[i]);
        D3D12_RANGE none = {0,0}; readbacks[i]->Unmap(0,&none);
        if (!good) return false;
    }
    FILE *meta = nullptr;
    const std::wstring path = std::wstring(folder)+L"\\proof.json";
    if (_wfopen_s(&meta,path.c_str(),L"wb") || !meta) return false;
    const auto desc = g_hdr_output->GetDesc();
    fprintf(meta,"{\"mapping\":\"" GFN_HDR_MAPPING "\",\"width\":%u,\"height\":%u,\"white\":%.9g,\"bypass\":%s,"
        "\"fence\":%llu,\"capture_format\":%u,\"output_format\":%u,\"timing_evidence\":false,"
        "\"manifest_sha256\":\"%s\",\"hwnd\":%llu,\"pid\":%lu,\"generation\":%llu,\"capture\":%llu,\"source_qpc\":%llu,"
        "\"sha256\":{\"source.fp16\":\"%s\",\"output.fp16\":\"%s\",\"proxy-in.rgba\":\"%s\",\"proxy-out.rgba\":\"%s\"}}",
        UINT(desc.Width),desc.Height,g_hdr_frame_white,bypass?"true":"false",fence,
        unsigned(g_dda_d12->GetDesc().Format),unsigned(desc.Format),manifest_hash,
        static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(g_wgc_hwnd)),target_pid,
        g_capture_generation,g_frame_stamp.capture,g_frame_stamp.source_qpc,hashes[0],hashes[1],hashes[2],hashes[3]);
    const bool good = !ferror(meta); const int closed = fclose(meta);
    completed = good && !closed;
    return completed;
}
