#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

typedef FARPROC (__stdcall *HostResolveFn)(void *, const char *);
typedef void *(__cdecl *SexyCreateGameFn)(HWND, const char *, int, void *, HostResolveFn);
typedef void (__cdecl *SexyDeleteGameFn)(void *);
typedef void (__cdecl *SexyGetDimensionsFn)(void *, int *, int *);
typedef int (__cdecl *SexyProcessMsgFn)(void *, UINT, WPARAM, LPARAM, LRESULT *);
typedef int (__cdecl *SexyUpdateStateFn)(void *);
typedef void (__cdecl *SexyReceiveNotificationFn)(void *, const char *, const char *);

static SexyProcessMsgFn process_msg;
static SexyReceiveNotificationFn receive_notification;
static void *game;
static HMODULE game_module;

typedef struct HostContext {
    HWND hwnd;
    int width;
    int height;
} HostContext;

static HostContext host;

static void trace_line(const char *label, const char *value) {
#ifdef BWA_TRACE
    HANDLE file = CreateFileA("bwa_launcher.log", FILE_APPEND_DATA, FILE_SHARE_READ,
                              NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD written;
    char line[256];
    if (file == INVALID_HANDLE_VALUE) return;
    wsprintfA(line, "%s%s%s\r\n", label, value ? ": " : "", value ? value : "");
    OutputDebugStringA(line);
    WriteFile(file, line, lstrlenA(line), &written, NULL);
    CloseHandle(file);
#else
    (void)label;
    (void)value;
#endif
}

static int __stdcall host_getparam(void *context, const char *name, char *value, int capacity) {
    const char *result = "";
    trace_line("getparam", name);
    (void)context;
    if (name) {
        if (!lstrcmpiA(name, "pc_scorebroadcast")) result = "3";
        /* There is no web ad interstitial in this host. */
        else if (!lstrcmpiA(name, "pc_sendgamebreaks")) result = "0";
        else if (!lstrcmpiA(name, "NumExtrasLoaded")) result = "3";
        else if (!lstrcmpiA(name, "Chapter2URL")) result = "bwachapter2.cab";
        else if (!lstrcmpiA(name, "Chapter3URL")) result = "bwachapter3.cab";
        else if (!lstrcmpiA(name, "Chapter4URL")) result = "bwachapter4.cab";
        else if (!lstrcmpiA(name, "ZoneScript")) result = "true";
        else if (!lstrcmpiA(name, "focuspause")) result = "true";
        else if (!lstrcmpiA(name, "ShowUpsell")) result = "false";
    }
    if (value && capacity > 0) lstrcpynA(value, result, capacity);
    return lstrlenA(result) + 1;
}

static void __stdcall host_notify(void *context, const char *method, const char *param) {
    trace_line("notify", method);
    HostContext *ctx = (HostContext *)context;
    (void)param;
    if (!ctx || !ctx->hwnd || !method) return;
    if (lstrcmpiA(method, "SessionReady") == 0)
        PostMessageA(ctx->hwnd, WM_APP + 1, 0, 0);
    else if (lstrcmpiA(method, "GameReady") == 0)
        PostMessageA(ctx->hwnd, WM_APP + 2, 0, 0);
    else if (lstrcmpiA(method, "GameBreak") == 0)
        PostMessageA(ctx->hwnd, WM_APP + 3, 0, 0);
    /* The original browser wrapper answers GameEnd with GameMenu. Without
       this acknowledgement the demo remains behind its closed end curtain. */
    else if (lstrcmpiA(method, "GameEnd") == 0)
        PostMessageA(ctx->hwnd, WM_APP + 4, 0, 0);
}

static void __stdcall host_setdrawparams(void *context, float scale,
                                         const char *a, const char *b, const char *c) {
    trace_line("setdrawparams", NULL);
    (void)context; (void)scale; (void)a; (void)b; (void)c;
}

static void __stdcall host_drawtodc(void *context, HDC source) {
    trace_line("drawtodc", NULL);
    HostContext *ctx = (HostContext *)context;
    HDC destination;
    if (!ctx || !ctx->hwnd || !source) return;
    destination = GetDC(ctx->hwnd);
    if (destination) {
        BitBlt(destination, 0, 0, ctx->width, ctx->height, source, 0, 0, SRCCOPY);
        ReleaseDC(ctx->hwnd, destination);
    }
}

static HMODULE __stdcall host_getdllhandle(void *context) {
    trace_line("getdllhandle", NULL);
    (void)context;
    return game_module;
}

static void __stdcall host_urlnavigate(void *context, const char *url, const char *target) {
    trace_line("urlnavigate", url);
    (void)context; (void)url; (void)target;
}

static FARPROC __stdcall host_resolve(void *context, const char *name) {
    (void)context;
    trace_line("resolve", name);
    if (!lstrcmpiA(name, "getparam")) return (FARPROC)host_getparam;
    if (!lstrcmpiA(name, "notify")) return (FARPROC)host_notify;
    if (!lstrcmpiA(name, "setdrawparams")) return (FARPROC)host_setdrawparams;
    if (!lstrcmpiA(name, "drawtodc")) return (FARPROC)host_drawtodc;
    if (!lstrcmpiA(name, "getdllhandle")) return (FARPROC)host_getdllhandle;
    if (!lstrcmpiA(name, "urlnavigate")) return (FARPROC)host_urlnavigate;
    /* The 2007 DLL requests getdllhandle last; tolerate its non-terminated label. */
    return (FARPROC)host_getdllhandle;
}

static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    LRESULT result = 0;
    if (message == WM_APP + 1 && game && receive_notification) {
        receive_notification(game, "SessionStart", "");
        return 0;
    }
    if (message == WM_APP + 2 && game && receive_notification) {
        receive_notification(game, "GameStart", "");
        return 0;
    }
    if (message == WM_APP + 3 && game && receive_notification) {
        receive_notification(game, "GameContinue", "");
        return 0;
    }
    if (message == WM_APP + 4 && game && receive_notification) {
        receive_notification(game, "GameMenu", "");
        return 0;
    }
    if (game && process_msg) {
        char number[32];
        wsprintfA(number, "%u", message);
        trace_line("process message", number);
        if (process_msg(game, message, wparam, lparam, &result)) return result;
        trace_line("message not handled", number);
    }
    if (message == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, message, wparam, lparam);
}

static FARPROC required(HMODULE module, const char *name) {
    FARPROC proc = GetProcAddress(module, name);
    if (!proc) {
        char message[256];
        wsprintfA(message, "BookwormAdventures.dll does not export %s", name);
        MessageBoxA(NULL, message, "Bookworm launcher", MB_ICONERROR);
        ExitProcess(2);
    }
    return proc;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command_line, int show) {
    char executable_path[MAX_PATH];
    char *separator;
    HMODULE dll;
    SexyCreateGameFn create_game;
    SexyDeleteGameFn delete_game;
    SexyGetDimensionsFn get_dimensions;
    SexyUpdateStateFn update_state;
    SexyReceiveNotificationFn notify;
    WNDCLASSA wc;
    RECT rect;
    HWND hwnd;
    MSG msg;
    int width = 640, height = 480;
    int state = 0;

    (void)previous;
    /* PopCap resolves properties and assets relative to the process CWD.  Make
       that deterministic when this launcher is started from another folder. */
    if (GetModuleFileNameA(NULL, executable_path, MAX_PATH)) {
        separator = executable_path + lstrlenA(executable_path);
        while (separator > executable_path && separator[-1] != '\\' && separator[-1] != '/')
            --separator;
        if (separator > executable_path) {
            separator[-1] = '\0';
            SetCurrentDirectoryA(executable_path);
        }
    }
    dll = LoadLibraryA("BookwormAdventures.dll");
    if (!dll) {
        MessageBoxA(NULL, "Could not load BookwormAdventures.dll", "Bookworm launcher", MB_ICONERROR);
        return 1;
    }
    game_module = dll;

    create_game = (SexyCreateGameFn)required(dll, "SexyCreateGame");
    delete_game = (SexyDeleteGameFn)required(dll, "SexyDeleteGame");
    get_dimensions = (SexyGetDimensionsFn)required(dll, "SexyGetDimensions");
    process_msg = (SexyProcessMsgFn)required(dll, "SexyProcessMsg");
    update_state = (SexyUpdateStateFn)required(dll, "SexyUpdateState");
    notify = (SexyReceiveNotificationFn)required(dll, "SexyReceiveNotification");
    receive_notification = notify;

    ZeroMemory(&wc, sizeof(wc));
    wc.style = CS_HREDRAW | CS_VREDRAW | CS_OWNDC;
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wc.lpszClassName = "BookwormAdventuresHost";
    if (!RegisterClassA(&wc)) return 3;

    rect.left = rect.top = 0;
    rect.right = width;
    rect.bottom = height;
    AdjustWindowRect(&rect, WS_OVERLAPPEDWINDOW, FALSE);
    hwnd = CreateWindowA(wc.lpszClassName, "Bookworm Adventures", WS_OVERLAPPEDWINDOW,
                         CW_USEDEFAULT, CW_USEDEFAULT, rect.right - rect.left,
                         rect.bottom - rect.top, NULL, NULL, instance, NULL);
    if (!hwnd) return 5;
    trace_line("window created", NULL);
    host.hwnd = hwnd;

    trace_line("before SexyCreateGame", NULL);
    game = create_game(hwnd, command_line ? command_line : "", 1, &host, host_resolve);
    trace_line("after SexyCreateGame", game ? "success" : "null");
    if (!game) {
        MessageBoxA(NULL, "SexyCreateGame failed", "Bookworm launcher", MB_ICONERROR);
        return 4;
    }
    trace_line("before SexyGetDimensions", NULL);
    get_dimensions(game, &width, &height);
    trace_line("after SexyGetDimensions", NULL);
    host.width = width;
    host.height = height;
    rect.left = rect.top = 0;
    rect.right = width;
    rect.bottom = height;
    AdjustWindowRect(&rect, WS_OVERLAPPEDWINDOW, FALSE);
    SetWindowPos(hwnd, NULL, 0, 0, rect.right - rect.left, rect.bottom - rect.top,
                 SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);

    for (;;) {
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) goto done;
            TranslateMessage(&msg);
            DispatchMessageA(&msg);
        }
        state = update_state(game);
        if (state == -2) break;
        Sleep(1);
    }

done:
    if (state != -2) delete_game(game);
    else {
        char state_text[32];
        wsprintfA(state_text, "%d", state);
        trace_line("engine stopped", state_text);
    }
    game = NULL;
    if (state != -2) FreeLibrary(dll);
    return state == -2 ? 0 : (int)msg.wParam;
}
