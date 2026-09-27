#pragma once

// Independent implementation of two color invariants, not a copied tone mapper.
// For positive luminance, compress negative scRGB channels toward neutral using
// one scalar. This preserves luminance and the RGB direction away from neutral.
// Limit neural edits by one scalar as well, rather than clipping their channels.
#define GFN_HDR_MAPPING "color-preserving"
#define GFN_HDR_COLOR_FUNCTIONS \
    "float3 ProxyGamut(float3 c) {\n" \
    " float low=min(c.r,min(c.g,c.b)); if(low>=0) return c;\n" \
    " float y=dot(c,float3(.2126,.7152,.0722)); if(y<=0) return 0;\n" \
    " float scale=y/(y-low); return max(y+(c-y)*scale,0); }\n" \
    "float3 LimitEdit(float3 d) {\n" \
    " float peak=max(abs(d.r),max(abs(d.g),abs(d.b)));\n" \
    " if(peak<=.25) return d; return d*(.25/peak); }\n"
