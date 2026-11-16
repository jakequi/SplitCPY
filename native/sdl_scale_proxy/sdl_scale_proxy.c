// SplitCPY SDL3 scale-mode proxy
//
// scrcpy never sets a texture scale mode, so SDL always scales the video with
// bilinear filtering (soft). This DLL is installed as bin/SDL3.dll in front of
// the real SDL (renamed bin/SDL3_real.dll). Every SDL function is forwarded
// straight to the real DLL by the linker (see build.py, which generates the
// .def); only texture creation is wrapped, to apply the scale mode named in
// the SPLITCPY_SCALE_MODE environment variable:
//
//   linear    smooth (SDL's default)
//   nearest   sharp, blocky pixels
//   pixelart  sharp pixels with smoothed edges (SDL 3.4+; falls back to nearest)
//
// Unset or unknown = untouched, so scrcpy behaves exactly as without the proxy.
//
// Build: python native/sdl_scale_proxy/build.py

#include <windows.h>
#include <stdbool.h>

typedef struct SDL_Renderer SDL_Renderer;
typedef struct SDL_Texture SDL_Texture;
typedef unsigned int SDL_PropertiesID;

typedef SDL_Texture *(*PFN_CreateTextureWithProperties)(SDL_Renderer *, SDL_PropertiesID);
typedef SDL_Texture *(*PFN_CreateTexture)(SDL_Renderer *, unsigned int, int, int, int);
typedef bool (*PFN_SetTextureScaleMode)(SDL_Texture *, int);

// SDL_ScaleMode values
#define MODE_NONE (-1)
#define MODE_NEAREST 0
#define MODE_LINEAR 1
#define MODE_PIXELART 2

static volatile LONG g_ready = 0;
static PFN_CreateTextureWithProperties p_create_with_props;
static PFN_CreateTexture p_create;
static PFN_SetTextureScaleMode p_set_scale;
static int g_mode = MODE_NONE;

static void init(void)
{
    if (g_ready)
        return;
    HMODULE real = GetModuleHandleA("SDL3_real.dll");
    if (!real)
        real = LoadLibraryA("SDL3_real.dll");
    if (real) {
        p_create_with_props = (PFN_CreateTextureWithProperties)GetProcAddress(real, "SDL_CreateTextureWithProperties");
        p_create = (PFN_CreateTexture)GetProcAddress(real, "SDL_CreateTexture");
        p_set_scale = (PFN_SetTextureScaleMode)GetProcAddress(real, "SDL_SetTextureScaleMode");
    }
    char value[32];
    DWORD n = GetEnvironmentVariableA("SPLITCPY_SCALE_MODE", value, sizeof(value));
    if (n > 0 && n < sizeof(value)) {
        if (!lstrcmpiA(value, "nearest"))
            g_mode = MODE_NEAREST;
        else if (!lstrcmpiA(value, "linear"))
            g_mode = MODE_LINEAR;
        else if (!lstrcmpiA(value, "pixelart"))
            g_mode = MODE_PIXELART;
    }
    InterlockedExchange(&g_ready, 1);
}

static SDL_Texture *apply(SDL_Texture *texture)
{
    if (texture && g_mode != MODE_NONE && p_set_scale) {
        if (!p_set_scale(texture, g_mode) && g_mode == MODE_PIXELART)
            p_set_scale(texture, MODE_NEAREST);  // renderer without pixel-art support
    }
    return texture;
}

__declspec(dllexport) SDL_Texture *SDL_CreateTextureWithProperties(SDL_Renderer *renderer, SDL_PropertiesID props)
{
    init();
    return p_create_with_props ? apply(p_create_with_props(renderer, props)) : NULL;
}

__declspec(dllexport) SDL_Texture *SDL_CreateTexture(SDL_Renderer *renderer, unsigned int format, int access, int w, int h)
{
    init();
    return p_create ? apply(p_create(renderer, format, access, w, h)) : NULL;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance;
    (void)reason;
    (void)reserved;
    return TRUE;
}
