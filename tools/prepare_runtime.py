"""Prepare the pinned Clockwork runtime for the Kirby executable."""

import argparse
import shutil
from pathlib import Path
from render_optimizations import pica, reuse_upload_buffer, shader, vertex_workers


def replace(text, original, replacement):
    if text.count(original) != 1:
        raise ValueError(f"Unexpected Clockwork source near {original[:90]!r}")
    return text.replace(original, replacement)


def remove_between(text, start, end, replacement=""):
    first = text.index(start)
    last = text.index(end, first)
    return text[:first] + replacement + text[last:]


def frontend(source):
    for header in ("handoff.h", "launcher.h"):
        source = replace(source, f'#include "{header}"\n', "")
    source = remove_between(source, "// a dump this executable", "void run(void (*start)")
    source = replace(source, "const char *cli_dump, bool force_launcher, bool play", "const char *cli_dump")
    source = replace(source,
        '        if (std::string problem; !hand_off_or_explain(cli_dump, &problem)) fatal("%s", problem.c_str());\n', "")
    source = remove_between(source, "    // the launcher, unless", "    if (device && !pica::gpu::init",
        '    game_path = s.game_path;\n    const std::string game_id = "kirby";\n')
    source = replace(source, 'SDL_SetAppMetadata("Clockwork", nullptr, "io.github.yw2recomp")',
                     'SDL_SetAppMetadata("Kirby: Triple Deluxe", nullptr, "local.kirby.triple.deluxe")')
    source = replace(source, '"Clockwork - Yo-kai Watch 2"', '"Kirby: Triple Deluxe"')
    source = replace(source, '"Clockwork: Yo-kai Watch 2 stopped"', '"Kirby: Triple Deluxe stopped"')
    source = replace(source, "    fatal_hook = show_fatal;",
                     '    if (!std::getenv("KIRBY_NO_DIALOG")) fatal_hook = show_fatal;')
    source = replace(source, 'if (s.gpu_renderer) {', 'if (s.gpu_renderer && !std::getenv("KIRBY_CPU_PICA")) {')
    source = replace(source, "    pica::set_hud_scale(float(s.hud_size) / 100.0f);",
        "    // Both screens share a render target. Keep all interface layers at their original scale.\n"
        "    pica::set_hud_scale(1.0f);")
    source = replace(source,
        "            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_SHADERS_SPIRV_BOOLEAN, true);",
        """            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_SHADERS_SPIRV_BOOLEAN, true);
#ifdef __linux__
            SDL_SetBooleanProperty(props, SDL_PROP_GPU_DEVICE_CREATE_VULKAN_REQUIRE_HARDWARE_ACCELERATION_BOOLEAN,
                                   !std::getenv("KIRBY_ALLOW_SOFTWARE_VULKAN"));
#endif""")
    source = replace(source,
        "    open_audio();\n    if (audio_stream) SDL_SetAudioStreamGain(audio_stream, float(s.volume) / 100.0f);",
        """    open_audio();
    if (audio_stream) {
        if (SDL_SetAudioStreamGain(audio_stream, float(s.volume) / 100.0f))
            LOG("audio: output volume %d%%", s.volume);
        else
            LOG("audio: cannot set the output volume (%s)", SDL_GetError());
    }""")
    source = replace(source, '#include "settings.h"', '#include "settings.h"\n#include "virtual_gamepad.h"\n#include <optional>')
    source = frontend_presentation(source)
    source = replace(source, 'SDL_ScaleMode scale_mode() {',
        '''SDL_Gamepad *open_pad(SDL_JoystickID id) {
    SDL_Gamepad *pad = SDL_OpenGamepad(id);
    if (!pad) return nullptr;
    for (const SDL_SensorType sensor : {SDL_SENSOR_ACCEL, SDL_SENSOR_GYRO})
        if (SDL_GamepadHasSensor(pad, sensor)) SDL_SetGamepadSensorEnabled(pad, sensor, true);
    return pad;
}

int16_t sensor_units(float value) {
    return std::isfinite(value) ? int16_t(std::clamp(std::round(value), -32767.0f, 32767.0f)) : 0;
}

void sample_motion(const std::vector<SDL_Gamepad *> &pads, float tilt, Input &in) {
    static uint64_t previous = SDL_GetTicksNS();
    static float angle = 0;
    const uint64_t now = SDL_GetTicksNS();
    const float seconds = std::min(float(now - previous) * 1.0e-9f, 0.05f);
    previous = now;
    constexpr float pi = 3.14159265f;
    const float turn_step = 2.5f * seconds;
    const float next = tilt != 0 ? std::clamp(angle + tilt * turn_step, -pi / 2, pi / 2)
                                 : angle - std::clamp(angle, -turn_step, turn_step);
    const float roll = seconds > 0 ? (next - angle) / seconds : 0;
    const bool using_manual_tilt = angle != 0 || next != 0 || tilt != 0;
    angle = next;
    constexpr float gyro_scale = 14.375f * (180 / pi);
    in.accel[0] = sensor_units(512 * std::sin(angle));
    in.accel[1] = sensor_units(-512 * std::cos(angle));
    in.gyro[2] = sensor_units(roll * gyro_scale);
    if (using_manual_tilt) return;

    for (SDL_Gamepad *pad : pads) {
        float sample[3]{};
        if (!SDL_GamepadSensorEnabled(pad, SDL_SENSOR_GYRO) ||
            !SDL_GetGamepadSensorData(pad, SDL_SENSOR_GYRO, sample, 3))
            continue;
        in.gyro[0] = sensor_units(-sample[0] * gyro_scale);
        in.gyro[1] = sensor_units(sample[1] * gyro_scale);
        in.gyro[2] = sensor_units(-sample[2] * gyro_scale);
        if (SDL_GamepadSensorEnabled(pad, SDL_SENSOR_ACCEL) &&
            SDL_GetGamepadSensorData(pad, SDL_SENSOR_ACCEL, sample, 3)) {
            constexpr float accel_scale = 512 / SDL_STANDARD_GRAVITY;
            in.accel[0] = sensor_units(sample[0] * accel_scale);
            in.accel[1] = sensor_units(-sample[1] * accel_scale);
            in.accel[2] = sensor_units(sample[2] * accel_scale);
        }
        break;
    }
}

SDL_ScaleMode scale_mode() {''')
    source = replace(source, "SDL_OpenGamepad(ids[j])) pads.push_back(g)", "open_pad(ids[j])) pads.push_back(g)")
    source = replace(source, "SDL_OpenGamepad(e.gdevice.which)) pads.push_back(g)",
        "open_pad(e.gdevice.which)) pads.push_back(g)")
    source = replace(source, '    input_script.apply(top_frames, in);',
        '    if (!std::getenv("KIRBY_TEST_GAMEPAD")) input_script.apply(top_frames, in);')
    source = replace(source, '    control.apply(in);',
        '    if (!std::getenv("KIRBY_TEST_GAMEPAD")) control.apply(in);')
    source = replace(source, '                if (e.key.scancode == SDL_SCANCODE_F9)',
        '''                if (e.key.scancode == SDL_SCANCODE_F4 && !e.key.repeat) {
                    s.frame_interpolation = !s.frame_interpolation;
                    pica::set_frame_interpolation(s.frame_interpolation);
                    s.save();
                    show_message(s.frame_interpolation ? "Frame interpolation on" : "Frame interpolation off");
                }
                if (e.key.scancode == SDL_SCANCODE_F9)''')
    source = replace(source, '            } else if (w == "shot" &&',
        '''            } else if (w == "draws" && std::sscanf(line.c_str(), "%*s %63s", arg) == 1) {
                pica::request_draw_log((dir / (std::string(arg) + ".txt")).string());
            } else if (w == "shot" &&''')
    source = replace(source, '    std::vector<SDL_Gamepad *> pads;',
        '''    std::optional<VirtualGamepad> test_pad;
    if (std::getenv("KIRBY_TEST_GAMEPAD")) {
        test_pad.emplace();
        if (!*test_pad) fatal("Cannot attach the test controller: %s", SDL_GetError());
        LOG("Gamepad input test is active: %s", SDL_GetGamepadNameForID(test_pad->instance()));
    }
    std::vector<SDL_Gamepad *> pads;''')
    source = replace(source, '        for (SDL_Gamepad *g : pads) in.buttons |= gamepad_buttons(g, in.circle_x, in.circle_y);',
        '''        if (test_pad) {
            Input scripted;
            input_script.apply(top_frames, scripted);
            control.apply(scripted);
            if (scripted.touching) {
                in.touching = true;
                in.touch_x = scripted.touch_x;
                in.touch_y = scripted.touch_y;
            }
            for (int i = 0; i < CONTROL_COUNT; ++i) {
                const int button = s.pad[i];
                if (CONTROLS[i].button && button >= 0 && button < SDL_GAMEPAD_BUTTON_COUNT)
                    test_pad->button(SDL_GamepadButton(button), (scripted.buttons & CONTROLS[i].button) != 0);
            }
            test_pad->axis(SDL_GAMEPAD_AXIS_LEFTX, int16_t(int(scripted.circle_x) * 32767 / CIRCLE_MAX));
            test_pad->axis(SDL_GAMEPAD_AXIS_LEFTY, int16_t(-int(scripted.circle_y) * 32767 / CIRCLE_MAX));
            SDL_UpdateJoysticks();
        }
        const bool *keys = SDL_GetKeyboardState(nullptr);
        float tilt = float(keys[SDL_SCANCODE_T]) - float(keys[SDL_SCANCODE_G]);
        for (SDL_Gamepad *g : pads) {
            in.buttons |= gamepad_buttons(g, in.circle_x, in.circle_y);
            const int roll_axis = SDL_GetGamepadAxis(g, SDL_GAMEPAD_AXIS_RIGHTX);
            if (std::abs(roll_axis) > 6500 && tilt == 0) tilt = roll_axis / 32768.0f;
        }
        sample_motion(pads, tilt, in);''')
    return replace(source, 'Input input() {', '''int poll_gamepad() {
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (!SDL_Init(SDL_INIT_GAMEPAD)) fatal("Gamepad initialization failed: %s", SDL_GetError());
    LOG("Waiting 35 seconds for physical gamepad input");
    SDL_Gamepad *device = nullptr;
    Input previous;
    bool saw_stick = false;
    uint32_t saw_buttons = 0;
    const uint64_t deadline = SDL_GetTicks() + 35000;
    while (SDL_GetTicks() < deadline) {
        SDL_PumpEvents();
        SDL_UpdateJoysticks();
        if (device && !SDL_GamepadConnected(device)) {
            SDL_CloseGamepad(device);
            device = nullptr;
            previous = {};
        }
        if (!device) {
            int count = 0;
            if (SDL_JoystickID *devices = SDL_GetGamepads(&count)) {
                for (int i = 0; i < count && !device; ++i) {
                    if (!SDL_IsJoystickVirtual(devices[i])) device = SDL_OpenGamepad(devices[i]);
                }
                SDL_free(devices);
            }
            if (device) LOG("Physical gamepad: %s", SDL_GetGamepadName(device));
        }
        if (device) {
            Input state;
            state.buttons = gamepad_buttons(device, state.circle_x, state.circle_y);
            const uint32_t pressed = state.buttons & ~previous.buttons;
            if (pressed) LOG("Physical gamepad guest buttons: %08x", pressed);
            const bool stick = state.circle_x || state.circle_y;
            if (stick && !saw_stick) LOG("Physical gamepad guest Circle Pad: %d/%d", state.circle_x, state.circle_y);
            saw_stick |= stick;
            saw_buttons |= pressed;
            previous = state;
            if (saw_stick && (saw_buttons & (BTN_A | BTN_X)) == (BTN_A | BTN_X)) break;
        }
        SDL_Delay(20);
    }
    if (device) SDL_CloseGamepad(device);
    SDL_Quit();
    LOG("Physical test summary: guest button mask %08x, left stick %s", saw_buttons, saw_stick ? "received" : "waiting");
    return saw_stick && (saw_buttons & (BTN_A | BTN_X)) == (BTN_A | BTN_X) ? 0 : 1;
}

int verify_gamepad() {
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (!SDL_Init(SDL_INIT_GAMEPAD)) fatal("Gamepad initialization failed: %s", SDL_GetError());
    int count = 0;
    if (SDL_JoystickID *devices = SDL_GetGamepads(&count)) {
        for (int i = 0; i < count; ++i)
            LOG("Connected gamepad: %s", SDL_GetGamepadNameForID(devices[i]));
        SDL_free(devices);
    }
    LOG("%d physical gamepad(s) detected before virtual test", count);
    Input motion;
    sample_motion({}, 0, motion);
    SDL_Delay(20);
    sample_motion({}, 1, motion);
    if (motion.gyro[2] <= 0 || motion.accel[0] <= 0)
        fatal("The clockwise motion sample did not reach the input state");
    {
        VirtualGamepad test_pad;
        if (!test_pad) fatal("Cannot create a virtual gamepad: %s", SDL_GetError());
        SDL_Gamepad *gamepad = SDL_OpenGamepad(test_pad.instance());
        if (!gamepad) fatal("Cannot open the test gamepad: %s", SDL_GetError());
        if (!test_pad.button(SDL_GAMEPAD_BUTTON_EAST, true) ||
            !test_pad.button(SDL_GAMEPAD_BUTTON_NORTH, true) ||
            !test_pad.button(SDL_GAMEPAD_BUTTON_START, true) ||
            !test_pad.axis(SDL_GAMEPAD_AXIS_LEFTX, 32767) ||
            !test_pad.axis(SDL_GAMEPAD_AXIS_LEFTY, -32767))
            fatal("Cannot set the virtual gamepad state: %s", SDL_GetError());
        SDL_UpdateJoysticks();
        int16_t x = 0, y = 0;
        const uint32_t buttons = gamepad_buttons(gamepad, x, y);
        if (buttons != (BTN_A | BTN_X | BTN_START) || x != CIRCLE_MAX || y != CIRCLE_MAX)
            fatal("Gamepad mapping mismatch: buttons %08x, stick %d/%d", buttons, x, y);
        SDL_CloseGamepad(gamepad);
    }
    SDL_Quit();
    LOG("Virtual SDL gamepad mapped jump, Whip Lash, Start, and the left stick");
    return 0;
}

Input input() {''')


def frontend_presentation(source):
    source = replace(source, '#include "settings.h"', '''#include "settings.h"
#ifdef _WIN32
#include "resolution_menu.h"
#else
#include "linux_upscaling.h"
#endif
#include <chrono>
#include <condition_variable>''')
    source = replace(source, "std::mutex frame_lock;", """std::mutex frame_lock;
std::condition_variable frame_ready;
bool lcd_present_pending = false;
std::vector<SDL_GPUTexture *> retired_gpu_frames;""")
    source = replace(source, "void run(void (*start)", """void finish_scanout(const std::vector<SDL_GPUTexture *> &retired) {
    {
        std::lock_guard lk(frame_lock);
        retired_gpu_frames.insert(retired_gpu_frames.end(), retired.begin(), retired.end());
        lcd_present_pending = frame_dirty[0] || frame_dirty[1] || !retired_gpu_frames.empty();
    }
    frame_ready.notify_one();
}

void run(void (*start)""")
    source = replace(source, "    pica::set_resolution_scale(s.resolution);", """#ifdef _WIN32
    ResolutionMenu resolution_menu(window, s, pica::gpu::active());
    resolution_menu.set_visible(!(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN));
#else
    LinuxUpscaling resolution_menu(s, pica::gpu::active());
#endif
    const auto menu_height = [&] {
#ifdef _WIN32
        return 0.0f;
#else
        return resolution_menu.height();
#endif
    };
    pica::set_resolution_scale(s.resolution);""")
    source = replace(source, """                    s.fullscreen = !(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN);
                    SDL_SetWindowFullscreen(window, s.fullscreen);""", """                    const bool fullscreen = !(SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN);
#ifdef _WIN32
                    if (fullscreen) resolution_menu.set_visible(false);
#endif
                    SDL_SetWindowFullscreen(window, fullscreen);
                    s.fullscreen = (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN) != 0;
#ifdef _WIN32
                    resolution_menu.set_visible(!s.fullscreen);
#else
                    relayout();
#endif""")
    source = source.replace("int(layout.h), SDL_LOGICAL_PRESENTATION_LETTERBOX);",
                            "int(layout.h + menu_height()), SDL_LOGICAL_PRESENTATION_LETTERBOX);")
    source = replace(source, "SDL_SetWindowSize(window, ww, int(float(ww) * layout.h / layout.w));",
                     "SDL_SetWindowSize(window, ww, int(float(ww) * (layout.h + menu_height()) / layout.w));")
    source = replace(source, "    auto show_message = [&](std::string text) { message = std::move(text), message_until = SDL_GetTicks() + 2500; };",
        """    bool redraw_requested = true;
    bool overlay_was_visible = false;
    unsigned window_frames = 0;
    uint64_t presentation_start = SDL_GetTicksNS();
    const bool log_presentation = std::getenv("KIRBY_FPS") != nullptr;
    auto show_message = [&](std::string text) {
        message = std::move(text);
        message_until = SDL_GetTicks() + 2500;
        redraw_requested = true;
    };""")
    source = replace(source, "    auto relayout = [&] {", "    auto relayout = [&] {\n        redraw_requested = true;")
    source = replace(source, "        while (SDL_PollEvent(&e)) {\n            switch (e.type)", """        while (SDL_PollEvent(&e)) {
            if ((e.type >= SDL_EVENT_WINDOW_FIRST && e.type <= SDL_EVENT_WINDOW_LAST) ||
                e.type == SDL_EVENT_RENDER_TARGETS_RESET)
                redraw_requested = true;
            switch (e.type)""")
    source = replace(source, """        {
            std::lock_guard lk(frame_lock);
            for (int i = 0; i < 2; i++) {""", """        const bool show_overlay = !message.empty() && SDL_GetTicks() < message_until;
        {
            std::unique_lock lk(frame_lock);
            if (!lcd_present_pending && !redraw_requested && show_overlay == overlay_was_visible &&
                !capture_requested && burst_left == 0) {
                // Wake on scanout and check input even while the guest screen is idle.
                frame_ready.wait_for(lk, std::chrono::milliseconds(4), [] { return lcd_present_pending; });
                continue;
            }
            lcd_present_pending = false;
            redraw_requested = false;
            overlay_was_visible = show_overlay;
            for (auto *texture : retired_gpu_frames) {
                const auto it = wrapped.find(texture);
                for (int i = 0; i < 2; ++i) {
                    if (gpu_frame[i] == texture) {
                        gpu_frame[i] = nullptr;
                        frame_dirty[i] = false;
                    }
                    if (it != wrapped.end() && shown_gpu[i] == it->second.tex)
                        shown_gpu[i] = nullptr;
                }
                // Wrappers belong to the window thread and outlive its previous submission.
                if (it != wrapped.end()) {
                    if (it->second.tex) SDL_DestroyTexture(it->second.tex);
                    wrapped.erase(it);
                }
                SDL_ReleaseGPUTexture(device, texture);
            }
            retired_gpu_frames.clear();
            for (int i = 0; i < 2; i++) {""")
    source = replace(source, "            case SDL_EVENT_KEY_DOWN:", """#ifndef _WIN32
            case SDL_EVENT_MOUSE_BUTTON_DOWN:
                if (e.button.button == SDL_BUTTON_LEFT) {
                    float x, y;
                    if (SDL_RenderCoordinatesFromWindow(renderer, e.button.x, e.button.y, &x, &y) &&
                        resolution_menu.click(x, y))
                        redraw_requested = true;
                }
                break;
#endif
            case SDL_EVENT_KEY_DOWN:""")
    source = replace(source, "            if (layout.touch_at(lx, ly, tx, ty)) {",
                     "            if (layout.touch_at(lx, ly - menu_height(), tx, ty)) {")
    source = replace(source, "            SDL_RenderTexture(renderer, t, &src, &layout.rect[i]);",
        """            SDL_FRect destination = layout.rect[i];
            destination.y += menu_height();
            SDL_RenderTexture(renderer, t, &src, &destination);""")
    source = replace(source, "                SDL_RenderRect(renderer, &layout.rect[i]);",
                     "                SDL_RenderRect(renderer, &destination);")
    source = replace(source, "        if (!message.empty() && SDL_GetTicks() < message_until) {",
        """#ifndef _WIN32
        resolution_menu.draw(renderer, layout.w);
#endif
        if (show_overlay) {""")
    source = replace(source, "y = layout.h - th - 8;", "y = menu_height() + layout.h - th - 8;")
    source = replace(source, "                    shown_gpu[i] = gpu_texture(gpu_frame[i], frame_width[i], frame_height[i]);",
        """                    shown_gpu[i] = gpu_texture(gpu_frame[i], frame_width[i], frame_height[i]);
                    if (i == 0 && log_presentation) {
                        static int last_width = 0, last_height = 0;
                        if (last_width != frame_width[i] || last_height != frame_height[i]) {
                            last_width = frame_width[i], last_height = frame_height[i];
                            LOG("graphics: Vulkan output %dx%d", last_width, last_height);
                        }
                    }""")
    return replace(source, "        SDL_RenderPresent(renderer); // paced by vsync", """        const bool presented = SDL_RenderPresent(renderer);
        if (log_presentation) {
            window_frames += presented;
            const uint64_t now = SDL_GetTicksNS();
            const uint64_t elapsed = now - presentation_start;
            if (elapsed >= 5 * SDL_NS_PER_SECOND) {
                LOG("Window: %.1f presentations/s", double(window_frames) * SDL_NS_PER_SECOND / double(elapsed));
                presentation_start = now;
                window_frames = 0;
            }
        }""")


def platform(source):
    source = replace(source, '#include "log.h"', '#include "log.h"\n#include <SDL3/SDL.h>')
    return remove_between(source, "        std::filesystem::path base;", "        std::filesystem::create_directories(d);",
        '''        const char *configured = std::getenv("KIRBY_DATA_DIR");
        const char *base = SDL_GetBasePath();
        auto d = configured && *configured ? std::filesystem::path(configured)
                                           : std::filesystem::path(base ? base : ".") / "userdata";
''')


def applets(source):
    source = replace(source, '#include "service.h"', '#include "service.h"\n#include "dump.h"')
    source = replace(source, "namespace hle {", "namespace hle {\nvoid reply_kirby_shared_font(Request &req);")
    source = replace(source, "        case 0x0101:", """        case 0x0058: { // GetProgramID for the calling process
            auto response = req.reply(3, 0);
            response.push64(dump().program_id());
            break;
        }
        case 0x0101:""")
    return replace(source, "        case 0x004B:", """        case 0x0044: // GetSharedFont
            reply_kirby_shared_font(req);
            break;
        case 0x004B:""")


def local_services(source):
    source = replace(source, "void register_stubs();", "void register_stubs();\nvoid register_kirby_account();")
    return replace(source, "    register_stubs();", "    register_stubs();\n    register_kirby_account();")


def loader_service(source):
    source = replace(source, "// ssl:C: TLS", """struct LoaderService : Service {
    LoaderService() : Service("ldr:ro") {}

    void handle(Request &request) override {
        constexpr uint32_t crs_header_size = 0x138;
        constexpr uint32_t buffer_too_small = 0xe0e12c1f;
        if (request.header() == 0x000100c2 && request.arg(1) < crs_header_size) {
            request.reply(1, 0, buffer_too_small);
            return;
        }
        unimplemented(*this, request);
    }
};

// ssl:C: TLS""")
    return replace(source, "void register_stubs() {",
        'void register_stubs() {\n    register_service({"ldr:ro"}, std::make_shared<LoaderService>());')


def console_settings(source):
    return replace(source, "        default:\n            unimplemented", """        case 0x0008: { // TranslateCountryInfo between old and new UK subdivisions
            uint32_t country_info = req.arg(0);
            const uint8_t subdivision = uint8_t(country_info >> 16);
            const uint8_t direction = uint8_t(req.arg(1));
            if ((country_info & 0xff00ffff) == 0x6e000000 && subdivision >= 3 && subdivision <= 7 && direction <= 1) {
                const uint32_t translated = 3 + (subdivision - 3 + (direction ? 1 : 4)) % 5;
                country_info = 0x6e000000 | (translated << 16);
            }
            auto response = req.reply(2, 0);
            response.push(country_info);
            break;
        }
        default:
            unimplemented""")


def call_trace(source):
    source = replace(source, '#include "recomp.h"', '#include "recomp.h"\n#ifdef _WIN32\n#include <windows.h>\n#endif')
    return replace(source, "    trace[trace_pos++ % TRACE_LEN] = {addr, ctx->r[14], ctx->r[13]};",
        """    trace[trace_pos++ % TRACE_LEN] = {addr, ctx->r[14], ctx->r[13]};
#ifdef _WIN32
    static const bool check_stack = std::getenv("KIRBY_TRACE_BOOT") != nullptr;
    if (check_stack) {
        thread_local const ULONG_PTR stack_floor = [&] {
            MEMORY_BASIC_INFORMATION stack{};
            if (!VirtualQuery(&ctx, &stack, sizeof stack)) return ULONG_PTR{0};
            return reinterpret_cast<ULONG_PTR>(stack.AllocationBase);
        }();
        if (stack_floor && reinterpret_cast<ULONG_PTR>(&ctx) - stack_floor < 65536)
            fatal("Low host stack during translated call to %08x (guest sp=%08x)", addr, ctx->r[13]);
    }
#endif""")


def translation_contract(source):
    source = replace(source, "typedef struct Ctx {", """typedef struct RecompUnwindFrame {
    jmp_buf resume;
    struct RecompUnwindFrame *previous;
    uint32_t sp;
    uint32_t return_pc;
} RecompUnwindFrame;

typedef struct Ctx {""")
    source = replace(source, "#include <stddef.h>", "#include <stddef.h>\n#include <setjmp.h>")
    source = replace(source, "    uint32_t tls;\n", """    uint32_t tls;
    /* scheduled by a tail branch, consumed by the nearest native call site */
    void (*pending_tail)(struct Ctx *ctx);
    RecompUnwindFrame *unwind_frame;
    uint32_t scheduling_ticks;
    uint32_t exclusive_address;
    uint32_t exclusive_kind;
""")
    return replace(source, "void recomp_call_indirect(Ctx *ctx, uint32_t target);",
        """void recomp_call_indirect(Ctx *ctx, uint32_t target);
void recomp_tail_indirect(Ctx *ctx, uint32_t target);
void recomp_restore_guest_context(Ctx *ctx, uint32_t target);
void recomp_preemption_point(Ctx *ctx);

static inline void recomp_poll_guest(Ctx *ctx) {
    if (++ctx->scheduling_ticks == 1024)
        recomp_preemption_point(ctx);
}

static inline void recomp_follow_tail(Ctx *ctx) {
    while (ctx->pending_tail) {
        RecompFn next = ctx->pending_tail;
        ctx->pending_tail = NULL;
        next(ctx);
    }
}""")


def kernel_dispatch(source):
    source = replace(source, "const auto start_time = std::chrono::steady_clock::now();",
        "auto start_time = std::chrono::steady_clock::now();")
    source = replace(source, "        timers.erase(timers.begin());\n        fn();",
        """        timers.erase(timers.begin());
        fn();
#ifdef __linux__
        // Give guest threads a chance to acquire the kernel lock when a slow
        // host keeps several periodic callbacks overdue.
        if (!timers.empty() && timers.begin()->first <= ticks())
            k().timer_cv.wait_for(lk, std::chrono::microseconds(100));
#endif""")
    source = replace(source, "void init(const GameImage &game) {",
        "void init(const GameImage &game) {\n    start_time = std::chrono::steady_clock::now();")
    source = replace(source, "void switch_to(Thread *next) {\n", """void switch_to(Thread *next) {
    if (k().current && k().current != next)
        k().current->ctx.exclusive_kind = 0;
""")
    source = replace(source, "    fn(&t->ctx);", "    fn(&t->ctx);\n    recomp_follow_tail(&t->ctx);")
    source = replace(source, "    fn(&main->ctx);", "    fn(&main->ctx);\n    recomp_follow_tail(&main->ctx);")
    source = replace(source, "void recomp_call_indirect(Ctx *ctx, uint32_t target) {",
        """void recomp_call_indirect(Ctx *ctx, uint32_t target) {
    recomp_tail_indirect(ctx, target);
    recomp_follow_tail(ctx);
}

void recomp_tail_indirect(Ctx *ctx, uint32_t target) {""")
    source = replace(source, "    fn(ctx);", "    ctx->pending_tail = fn;")
    source = replace(source, "void recomp_unhandled(Ctx *ctx, uint32_t addr, const char *what) {",
        """void recomp_preemption_point(Ctx *ctx) {
    ctx->scheduling_ticks = 0;
    std::unique_lock lock(kernel::k().lock);
    kernel::maybe_preempt(lock);
}

void recomp_unhandled(Ctx *ctx, uint32_t addr, const char *what) {""")
    return replace(source, "    static const char *states[] =",
        "    if (!lk.owns_lock()) return;\n    static const char *states[] =")


def motion_service(source):
    source = replace(source, "#include <cstring>", "#include <algorithm>\n#include <cstring>")
    source = replace(source, "accel_index = 7, gyro_index = 7;", "accel_index = 7, gyro_index = 31;")
    source = replace(source, "    // one update of every ring, like the HID module's sampling",
        """    void write_motion(uint32_t base, uint32_t &index, uint32_t count, uint64_t now,
                      const int16_t (&raw)[3], const int16_t (&sample)[3]) {
        index = (index + 1) % count;
        if (index == 0) {
            uint64_t previous;
            std::memcpy(&previous, mem::ptr(shared->address + base), sizeof previous);
            write64(base + 8, previous);
            write64(base, now);
        }
        std::memcpy(mem::ptr(shared->address + base + 0x18), raw, sizeof raw);
        std::memcpy(mem::ptr(shared->address + base + 0x20 + index * sizeof sample), sample, sizeof sample);
        write32(base + 0x10, index);
    }

    // one update of every ring, like the HID module's sampling""")
    source = remove_between(source, "        // accelerometer and gyroscope: device at rest", "        pad0->signal();",
        """        // HID reports the uncalibrated samples in the sensor's own axes.
        auto raw_acceleration = [](int value) { return int16_t(std::clamp(value, -32768, 32767)); };
        const int16_t raw_accel[] = {raw_acceleration(-2 * in.accel[0]), raw_acceleration(-2 * in.accel[2]),
                                    raw_acceleration(2 * in.accel[1])};
        const int16_t raw_gyro[] = {in.gyro[0], in.gyro[2], int16_t(-in.gyro[1])};
        write_motion(ACCEL, accel_index, 8, now, raw_accel, in.accel);
        write_motion(GYRO, gyro_index, 32, now, raw_gyro, in.gyro);

""")
    return replace(source, "            for (int i = 0; i < 5; i++) r.push(0);",
        """            constexpr int16_t unit = 6700;
            const int16_t calibration[10] = {0, unit, -unit, 0, unit, -unit, 0, unit, -unit, 0};
            for (size_t i = 0; i < 10; i += 2)
                r.push(uint16_t(calibration[i]) | (uint32_t(uint16_t(calibration[i + 1])) << 16));""")


def display_statistics(source):
    source = replace(source, "#include <array>", "#include <array>\n#include <chrono>")
    source = replace(source, "            present();\n            raise(PDC0);", """            // A scanout retired after this snapshot stays alive until the next VBlank.
            auto retired = pica::gpu::take_retired_scanouts();
            present();
            frontend::finish_scanout(retired);
            raise(PDC0);""")
    source = replace(source, "        lcd[screen] = {info[1], info[3], info[4]};",
        """        lcd[screen] = {info[1], info[3], info[4]};
        if (screen == 0) top_swap_pending = true;""")
    source = replace(source, "    std::mutex gx_lock;", """    std::mutex gx_lock;
    bool processing_queues = false;
    bool top_swap_pending = false;
    unsigned top_updates = 0;
    std::chrono::steady_clock::time_point statistics_start = std::chrono::steady_clock::now();""")
    source = replace(source, "        static int vblanks = 0;", """        if (top_swap_pending) {
            if (fps) ++top_updates;
            top_swap_pending = false;
        }
        static int vblanks = 0;""")
    source = replace(source, '            LOG("fps: %.1f  (per second:', '''            const auto now = std::chrono::steady_clock::now();
            const double elapsed = std::chrono::duration<double>(now - statistics_start).count();
            LOG("Top screen: %.1f framebuffer updates/s (%u in %.2f s)", top_updates / elapsed, top_updates, elapsed);
            statistics_start = now;
            top_updates = 0;
            LOG("Top-screen transfers/s: %.1f  (per second:''')
    source = replace(source, "                frames_rendered / 5.0,", "                frames_rendered / elapsed,")
    source = replace(source, "    unsigned top_updates = 0;",
        "    unsigned top_updates = 0;\n    std::array<uint32_t, 2> top_left_eyes{};\n    std::array<uint32_t, 2> top_right_eyes{};")
    source = replace(source, "        LOG_GPU(\"screen %u shows %08x (stride %u, format %u)\", screen, info[1], info[3], info[4]);",
        '        LOG_GPU("screen %u shows %08x (right %08x, stride %u, format %u)", screen, info[1], info[2], info[3], info[4]);')
    source = replace(source, "        if (screen == 0) top_swap_pending = true;",
        """        if (screen == 0) {
            top_swap_pending = true;
            const uint32_t left = info[1];
            const uint32_t right = info[2];
            if (left && left != top_left_eyes[0] && left != top_left_eyes[1])
                top_left_eyes = {left, top_left_eyes[0]};
            // Remember both right-eye buffers as the game alternates between them.
            if (right && right != left && right != top_right_eyes[0] && right != top_right_eyes[1])
                top_right_eyes = {right, top_right_eyes[0]};
        }""")
    source = replace(source, "        case 0x03: // DisplayTransfer(in, out, in dims, out dims, flags)",
        "        case 0x03: { // DisplayTransfer(in, out, in dims, out dims, flags)")
    source = replace(source, "            pica::display_transfer(c[1], c[2], c[3], c[4], c[5]);",
        """            const bool displayed_left = c[2] == top_left_eyes[0] || c[2] == top_left_eyes[1];
            const bool known_right = c[2] == top_right_eyes[0] || c[2] == top_right_eyes[1];
            // With stereoscopy off both LCD eyes can name the same left buffer.
            // The guest can still copy the hidden eye into a separate buffer.
            const bool right_eye = c[2] && (c[4] >> 16) == frontend::TOP_WIDTH &&
                !displayed_left && (known_right || top_left_eyes[1]);
            pica::display_transfer(c[1], c[2], c[3], c[4], c[5], right_eye);""")
    source = replace(source, "        case 0x04: // TextureCopy", "        }\n        case 0x04: // TextureCopy")
    source = remove_between(source, "    void process_queue(", "    void handle(Request &req)",
        """    void process_queues(std::unique_lock<std::mutex> &lk) {
        // While a list runs without the guest CPU, another thread may enqueue
        // commands or trigger GSP again. Keep one consumer and drain live counts.
        if (processing_queues) return;
        processing_queues = true;
        bool processed;
        do {
            processed = false;
            for (uint32_t thread = 0; thread < threads; ++thread) {
                uint8_t *q = shm(0x800 + thread * 0x200);
                if (!q[1]) continue;
                const uint8_t index = q[0] % 15;
                uint32_t command[8];
                std::memcpy(command, q + 0x20 + index * 0x20, sizeof command);
                run_command(command, lk);
                q[0] = uint8_t((index + 1) % 15);
                --q[1];
                processed = true;
            }
        } while (processed);
        processing_queues = false;
    }

""")
    source = replace(source, "            for (uint32_t t = 0; t < threads; t++) process_queue(t, *req.lock);",
        "            process_queues(*req.lock);")
    return replace(source, "            top_updates = 0;",
        """            top_updates = 0;
            const unsigned presented = pica::gpu::take_interpolated_presentations();
            if (presented)
                LOG("Interpolated top-screen output: %.1f frames/s (%u in %.2f s)", presented / elapsed, presented, elapsed);""")


def display_transfer(source):
    source = replace(source,
        "void display_transfer(uint32_t in, uint32_t out, uint32_t in_dims, uint32_t out_dims, uint32_t flags) {",
        "void display_transfer(uint32_t in, uint32_t out, uint32_t in_dims, uint32_t out_dims, uint32_t flags, bool right_eye) {")
    source = replace(source, "    scene_frame_done(in_h);", "    if (!right_eye) scene_frame_done(out_h);")
    return replace(source, "gpu::display_transfer(in, out, in_w, in_h, out_w, out_h, flags)",
        "gpu::display_transfer(in, out, in_w, in_h, out_w, out_h, flags, right_eye)")


def lighting_textures(source):
    source = replace(source, "SDL_GPUTexture *lut_tex, *dummy_tex;", "SDL_GPUTexture *dummy_tex;")
    source = replace(source, "    SDL_GPUTexture *tex[3];",
        "    SDL_GPUTexture *tex[3];\n    SDL_GPUTexture *lut;")
    source = replace(source, """bool lut_upload = false;
uint32_t lut_version_done = ~0u, fog_done[128];
std::vector<float> lut_pixels(256 * 25 * 2);""",
        """struct LightingTexture {
    SDL_GPUTexture *texture = nullptr;
    bool lighting = false, fog = false;
    uint64_t last_use = 0, batch = 0;
    uint32_t lights[24][256];
    uint32_t fog_values[128];
};
LightingTexture lighting_textures[24];
LightingTexture *last_lighting_texture = nullptr;
uint32_t last_lighting_version = 0;
uint64_t lighting_clock = 0, lighting_batch = 1;

void discard_lighting_textures() {
    for (auto &entry : lighting_textures) {
        if (entry.texture) SDL_ReleaseGPUTexture(dev, entry.texture);
        entry.texture = nullptr;
    }
    last_lighting_texture = nullptr;
}""")
    source = remove_between(source, "void update_luts(", "float f16(",
        """SDL_GPUTexture *lookup_lighting_texture(bool lighting, bool fog) {
    if (!lighting && !fog) return dummy_tex;
    auto mark_used = [&](LightingTexture &entry) {
        entry.last_use = ++lighting_clock;
        entry.batch = lighting_batch;
        last_lighting_texture = &entry;
        last_lighting_version = lighting_lut_version;
        return entry.texture;
    };
    auto matches_fog = [&](const LightingTexture &entry) {
        return !fog || std::memcmp(entry.fog_values, fog_lut, sizeof fog_lut) == 0;
    };
    if (auto *last = last_lighting_texture;
        last && last->lighting == lighting && last->fog == fog &&
        (!lighting || last_lighting_version == lighting_lut_version) && matches_fog(*last))
        return mark_used(*last);

    auto *oldest = &lighting_textures[0];
    for (auto &entry : lighting_textures) {
        if (entry.texture && entry.lighting == lighting && entry.fog == fog &&
            (!lighting || std::memcmp(entry.lights, lighting_lut, sizeof lighting_lut) == 0) &&
            matches_fog(entry))
            return mark_used(entry);
        if (!entry.texture || (oldest->texture && entry.last_use < oldest->last_use))
            oldest = &entry;
    }

    // Bind each draw's own snapshot. Alternating lamp settings no longer split batches.
    if (oldest->texture && oldest->batch == lighting_batch) flush();
    if (oldest->texture) SDL_ReleaseGPUTexture(dev, oldest->texture);
    oldest->texture = make_texture(256, 25, SDL_GPU_TEXTUREFORMAT_R32G32_FLOAT,
                                   SDL_GPU_TEXTUREUSAGE_SAMPLER);
    oldest->lighting = lighting;
    oldest->fog = fog;
    float pixels[256 * 25 * 2]{};
    if (lighting) {
        std::memcpy(oldest->lights, lighting_lut, sizeof lighting_lut);
        for (int t = 0; t < 24; ++t) {
            for (int i = 0; i < 256; ++i) {
                const uint32_t value = oldest->lights[t][i];
                const float difference = float((value >> 12) & 0x7FF) / 2047.0f;
                pixels[(t * 256 + i) * 2] = float(value & 0xFFF) / 4095.0f;
                pixels[(t * 256 + i) * 2 + 1] = (value >> 23) & 1 ? -difference : difference;
            }
        }
    }
    if (fog) {
        std::memcpy(oldest->fog_values, fog_lut, sizeof fog_lut);
        for (int i = 0; i < 128; ++i) {
            const uint32_t value = oldest->fog_values[i];
            pixels[(24 * 256 + i) * 2] = float((value >> 13) & 0x7FF) / 2047.0f;
            pixels[(24 * 256 + i) * 2 + 1] = float(int32_t(value << 19) >> 19) / 2047.0f;
        }
    }
    std::vector<uint8_t> bytes(sizeof pixels);
    std::memcpy(bytes.data(), pixels, sizeof pixels);
    texture_uploads.push_back({oldest->texture, std::move(bytes), 256, 25});
    return mark_used(*oldest);
}

""")
    source = replace(source, "    if (lut_upload) total += lut_pixels.size() * sizeof(float);\n", "")
    source = replace(source, "    for (auto &u : texture_uploads) total += u.rgba.size();",
        """    // R32G32_FLOAT lighting texture copies need an eight-byte-aligned buffer offset.
    const auto aligned = [](size_t bytes) { return (bytes + 7) & ~size_t(7); };
    for (auto &u : texture_uploads) total += aligned(u.rgba.size());""")
    source = replace(source, "        at += u.rgba.size();", "        at += aligned(u.rgba.size());")
    source = replace(source, "        texture_uploads.clear(), surface_loads.clear();\n        return;",
        "        texture_uploads.clear(), surface_loads.clear();\n        discard_lighting_textures();\n        return;")
    source = remove_between(source, "    size_t lut_at = at;", "    size_t vert_at = at;")
    source = remove_between(source, "    if (lut_upload) {", "    if (vbytes) {")
    source = replace(source, "    lut_upload = false;\n", "")
    source = replace(source,
        "    lut_tex = make_texture(256, 25, SDL_GPU_TEXTUREFORMAT_R32G32_FLOAT, SDL_GPU_TEXTUREUSAGE_SAMPLER);\n", "")
    source = replace(source, "    std::memset(fog_done, 0xFF, sizeof fog_done);\n", "")
    source = replace(source, "    update_luts(lighting, fog);", "    d.lut = lookup_lighting_texture(lighting, fog);")
    source = replace(source, " && !lut_upload)", ")")
    binding = "{lut_tex, nearest_clamp}};"
    if source.count(binding) != 2:
        raise ValueError("Unexpected number of lighting texture bindings")
    source = source.replace(binding, "{d.lut, nearest_clamp}};")
    return replace(source, "    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);\n    batch.clear();",
        "    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);\n    ++lighting_batch;\n    batch.clear();")


def interpolation_history(source):
    source = replace(source, "    std::vector<GpuVertex> verts;",
        """    struct VertexHistory {
        float pos[4], quat[4], view[4];
        float screen_x = 0, screen_y = 0;

        explicit VertexHistory(const GpuVertex &v) {
            std::memcpy(pos, v.pos, sizeof pos);
            std::memcpy(quat, v.quat, sizeof quat);
            std::memcpy(view, v.view, sizeof view);
            if (pos[3] <= 1e-4f) return;
            screen_x = std::clamp(pos[0] / pos[3], -1.5f, 1.5f);
            screen_y = std::clamp(pos[1] / pos[3], -1.5f, 1.5f);
        }
    };
    std::vector<VertexHistory> verts;""")
    source = remove_between(source, "// a draw's mean place on screen:", "// last frame's draw like")
    source = replace(source,
        "void lerp_vertex(GpuVertex &out, const GpuVertex &last, const GpuVertex &now, float t) {",
        "void lerp_vertex(GpuVertex &out, const FrameRecord::VertexHistory &last, const GpuVertex &now, float t) {")
    source = replace(source, """        this_frame.verts.insert(this_frame.verts.end(), vertices.begin() + d.first,
                                vertices.begin() + d.first + d.count);
        float cx, cy;
        centroid(&vertices[d.first], d.count, cx, cy);""",
        """        // Store only the attributes needed to interpolate, and project
        // each vertex once for both draw matching and movement detection.
        double x = 0, y = 0;
        uint32_t visible = 0;
        for (uint32_t i = d.first; i < d.first + d.count; ++i) {
            const auto &vertex = this_frame.verts.emplace_back(vertices[i]);
            if (vertex.pos[3] <= 1e-4f) continue;
            x += vertex.screen_x;
            y += vertex.screen_y;
            ++visible;
        }
        const float cx = visible ? float(x / visible) : 0.0f;
        const float cy = visible ? float(y / visible) : 0.0f;""")
    return replace(source, """                const GpuVertex &a = last_frame.verts[size_t(s) + k], &b = vertices[v + k];
                perspective |= std::fabs(b.pos[3] - 1.0f) > 1e-4f;
                if (a.pos[3] <= 1e-4f || b.pos[3] <= 1e-4f) continue;
                // movement on screen: a vertex next to the eye (ground under the camera) lands far
                // off it, where a small step is a huge one, and would make its whole draw look like
                // it jumped (then drawn where it is now, cracks open against its neighbours)
                auto on_screen = [](float c, float w) { return std::clamp(c / w, -1.5f, 1.5f); };
                moved += std::fabs(on_screen(a.pos[0], a.pos[3]) - on_screen(b.pos[0], b.pos[3])) +
                         std::fabs(on_screen(a.pos[1], a.pos[3]) - on_screen(b.pos[1], b.pos[3]));""",
        """                const auto &a = last_frame.verts[size_t(s) + k];
                const auto &b = this_frame.verts[vertex_start + v - d.first + k];
                perspective |= std::fabs(b.pos[3] - 1.0f) > 1e-4f;
                if (a.pos[3] <= 1e-4f || b.pos[3] <= 1e-4f) continue;
                moved += std::fabs(a.screen_x - b.screen_x) + std::fabs(a.screen_y - b.screen_y);""")


def vulkan_renderer(source):
    source = lighting_textures(source)
    source = replace(source, '#include "shaders.inc"',
        '#include <immintrin.h>\n#include "shaders.inc"')
    source = replace(source,
        """            float x0 = v0.a[POS] / w0, y0 = v0.a[POS + 1] / w0, x1 = v1.a[POS] / w1, y1 = v1.a[POS + 1] / w1;
            float x2 = v2.a[POS] / w2, y2 = v2.a[POS + 1] / w2;
            float area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0);""",
        """            // Divide the three clip positions in parallel with full precision.
            const __m128 w = _mm_setr_ps(w0, w1, w2, 1.0f);
            const __m128 x = _mm_div_ps(_mm_setr_ps(v0.a[POS], v1.a[POS], v2.a[POS], 0), w);
            const __m128 y = _mm_div_ps(_mm_setr_ps(v0.a[POS + 1], v1.a[POS + 1], v2.a[POS + 1], 0), w);
            const __m128 dx = _mm_sub_ps(x, _mm_shuffle_ps(x, x, _MM_SHUFFLE(0, 0, 0, 0)));
            const __m128 dy = _mm_sub_ps(y, _mm_shuffle_ps(y, y, _MM_SHUFFLE(0, 0, 0, 0)));
            const __m128 products = _mm_mul_ps(dx, _mm_shuffle_ps(dy, dy, _MM_SHUFFLE(3, 1, 2, 0)));
            const float area = _mm_cvtss_f32(_mm_shuffle_ps(products, products, _MM_SHUFFLE(1, 1, 1, 1))) -
                               _mm_cvtss_f32(_mm_shuffle_ps(products, products, _MM_SHUFFLE(2, 2, 2, 2)));""")
    source = replace(source, '#include "shaders.inc"', '#include "shaders.inc"\n#include "kirby_lcd.inc"')
    source = replace(source, "SPIRV_blit_lcd_frag, sizeof SPIRV_blit_lcd_frag", "kirby_lcd, sizeof kirby_lcd")
    source = replace(source, "uint64_t hash_bytes(const uint8_t *p, size_t n);",
        "uint64_t hash_guest_bytes(uint32_t addr, const uint8_t *p, size_t n);")
    source = replace(source, "return g ? hash_bytes(g, s.bytes()) : 0;",
        "return g ? hash_guest_bytes(s.addr, g, s.bytes()) : 0;")
    source = replace(source, "SDL_GPUSampler *sampler(bool linear,",
        """uint64_t hash_guest_bytes(uint32_t addr, const uint8_t *p, size_t n) {
    // Large atlases and render targets commonly retain the same guest bytes
    // across command lists. Compare them exactly before reusing their hash.
    if (n < 4096 || n > 1024 * 1024) return hash_bytes(p, n);
    struct Snapshot {
        uint32_t addr = 0;
        uint64_t hash = 0;
        std::vector<uint8_t> bytes;
    };
    static Snapshot snapshots[32];
    auto &snapshot = snapshots[((addr >> 7) ^ (addr >> 14) ^ (addr >> 21) ^ (n >> 9)) & 31];
    if (snapshot.addr == addr && snapshot.bytes.size() == n &&
        std::memcmp(snapshot.bytes.data(), p, n) == 0)
        return snapshot.hash;
    snapshot.addr = addr;
    snapshot.bytes.resize(n);
    std::memcpy(snapshot.bytes.data(), p, n);
    snapshot.hash = hash_bytes(snapshot.bytes.data(), n);
    return snapshot.hash;
}

SDL_GPUSampler *sampler(bool linear,""")
    source = replace(source, "if (fresh) known->second = hash_bytes(t.data, t.bytes);",
        "if (fresh) known->second = hash_guest_bytes(t.addr, t.data, t.bytes);")
    source = replace(source, "void interpolate_batch() {",
        """struct PackedScanout {
    uint32_t addr = 0;
    int first_row = 0, end_row = 0;
} packed_scanout;

void interpolate_batch() {""")
    source = replace(source, """    std::vector<GpuVertex> mid;
    for (DrawRec &d : batch) {
        uint32_t slots = uint32_t(this_frame.slots.size());
        this_frame.slots.resize(slots + d.tris, -1);
        for (uint32_t v = d.first; v < d.first + d.count; v += 3) {
            this_frame.slots[slots + tri_ids[v / 3]] = int32_t(this_frame.verts.size());
            this_frame.verts.insert(this_frame.verts.end(), vertices.begin() + v, vertices.begin() + v + 3);
        }""",
        """    static std::vector<GpuVertex> mid;
    mid.clear();
    for (DrawRec &d : batch) {
        // Bottom-screen draws are displayed at guest cadence.
        if (d.color->height == 320) continue;
        // The original eye renders remain intact. Only the displayed
        // part of the packed surface needs an intermediate image.
        if (d.color->height == 800 && d.color->addr == packed_scanout.addr &&
            (d.scissor.y + d.scissor.h <= packed_scanout.first_row ||
             d.scissor.y >= packed_scanout.end_row))
            continue;
        const uint32_t slots = uint32_t(this_frame.slots.size());
        const uint32_t vertex_start = uint32_t(this_frame.verts.size());
        this_frame.slots.resize(slots + d.tris, -1);
        for (uint32_t v = d.first; v < d.first + d.count; v += 3)
            this_frame.slots[slots + tri_ids[v / 3]] = int32_t(vertex_start + v - d.first);
        this_frame.verts.insert(this_frame.verts.end(), vertices.begin() + d.first,
                                vertices.begin() + d.first + d.count);""")
    source = replace(source, "d.interpolated = interp_this && d.color->height != 320;",
        "d.interpolated = interp_this;")
    source = interpolation_history(source)
    source = replace(source, "void upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf) {",
        """SDL_GPUBuffer *batch_vertices = nullptr;
uint32_t vertex_capacity = 0;

void upload_pending(SDL_GPUCommandBuffer *cmd, SDL_GPUBuffer **vbuf) {""")
    source = replace(source, """    if (vbytes) {
        SDL_GPUBufferCreateInfo bi{SDL_GPU_BUFFERUSAGE_VERTEX, uint32_t(vbytes), 0};
        *vbuf = SDL_CreateGPUBuffer(dev, &bi);
        if (!*vbuf) out_of_gpu_memory(), *vbuf = SDL_CreateGPUBuffer(dev, &bi);
        if (*vbuf) { // otherwise this batch isn't drawn
            SDL_GPUTransferBufferLocation src{tb, uint32_t(vert_at)};
            SDL_GPUBufferRegion dst{*vbuf, 0, uint32_t(vbytes)};
            SDL_UploadToGPUBuffer(copy, &src, &dst, false);
        }
    }""",
        """    if (vbytes > vertex_capacity && vbytes <= UINT32_MAX) {
        const uint64_t rounded = (uint64_t(vbytes) + 65535) & ~uint64_t(65535);
        SDL_GPUBufferCreateInfo info{SDL_GPU_BUFFERUSAGE_VERTEX, uint32_t(std::min<uint64_t>(rounded, UINT32_MAX)), 0};
        auto *larger = SDL_CreateGPUBuffer(dev, &info);
        if (!larger) {
            out_of_gpu_memory();
            larger = SDL_CreateGPUBuffer(dev, &info);
        }
        if (larger) {
            if (batch_vertices) SDL_ReleaseGPUBuffer(dev, batch_vertices);
            batch_vertices = larger;
            vertex_capacity = info.size;
        }
    }
    if (vbytes && vbytes <= vertex_capacity) {
        *vbuf = batch_vertices;
        SDL_GPUTransferBufferLocation src{tb, uint32_t(vert_at)};
        SDL_GPUBufferRegion dst{batch_vertices, 0, uint32_t(vbytes)};
        // Cycle when an earlier submission is still consuming the vertex data.
        SDL_UploadToGPUBuffer(copy, &src, &dst, true);
    }""")
    source = replace(source, "    if (vbuf) SDL_ReleaseGPUBuffer(dev, vbuf);\n", "")
    source = replace(source, "void begin_draw() {",
        """void begin_draw() {
    static const bool timings = std::getenv("KIRBY_GPU_TIMINGS") != nullptr;
    static int64_t surface_ns = 0, texture_ns = 0, lighting_ns = 0, rest_ns = 0;
    static int64_t sampled_draws = 0;
    const int64_t start = timings ? now_ns() : 0;""")
    source = replace(source, "    FragUniforms &u = d.fu;",
        """    const int64_t after_surface = timings ? now_ns() : 0;
    FragUniforms &u = d.fu;""")
    source = replace(source, "    bool wbuffer = !(regs[DEPTHMAP_ENABLE] & 1);",
        """    const int64_t after_textures = timings ? now_ns() : 0;
    bool wbuffer = !(regs[DEPTHMAP_ENABLE] & 1);""")
    source = replace(source, "    // fixed-function state\n    PipelineKey k{};",
        """    const int64_t after_lighting = timings ? now_ns() : 0;
    // fixed-function state
    PipelineKey k{};""")
    source = replace(source, "    cur_skip = false;\n}",
        """    cur_skip = false;
    if (timings) {
        surface_ns += after_surface - start;
        texture_ns += after_textures - after_surface;
        lighting_ns += after_lighting - after_textures;
        rest_ns += now_ns() - after_lighting;
        if (++sampled_draws == 2000) {
            LOG("GPU setup over 2000 draws: surfaces %.1f ms, textures %.1f ms, lighting %.1f ms, state %.1f ms",
                surface_ns / 1e6, texture_ns / 1e6, lighting_ns / 1e6, rest_ns / 1e6);
            sampled_draws = surface_ns = texture_ns = lighting_ns = rest_ns = 0;
        }
    }
}""")
    source = replace(source, "uint32_t flags) {\n    if (!ok) return false;\n    list_hashes.clear();\n    if (in_h == 400)",
        "uint32_t flags, bool right_eye) {\n    if (!ok) return false;\n    list_hashes.clear();\n"
        "    if (in_h == 400 && out_h == 400 && !right_eye)")
    source = replace(source, "    bool top = in_h == 400;", "    const bool top = in_h == 400 && out_h == 400 && !right_eye;")
    source = replace(source,
        "    for (auto &s : surfaces)\n        if (!s->depth && s->addr == p && s->width == in_w && s->height == in_h) src = s.get();",
        """    const uint32_t format = (flags >> 8) & 7;
    // The lower LCD copies 320 rows starting at row 80 of Kirby's shared 400-row target.
    const bool cropped_lcd = in_w == 240 && in_h == 400 && out_w == 240 && out_h == 320 && (flags & 4);
    const uint32_t copied_rows = cropped_lcd ? out_h : in_h;
    uint32_t source_row = 0;
    for (auto &s : surfaces) {
        if (s->depth || s->reload || s->width != in_w || s->format != format || p < s->addr) continue;
        const uint32_t row_bytes = s->width * s->bpp();
        const uint32_t offset = p - s->addr;
        if (offset % (8 * row_bytes)) continue;
        const uint32_t row = offset / row_bytes;
        if (row >= s->height || copied_rows > s->height - row) continue;
        // In a 256x800 stereo surface, both eyes share one image. Scan out each view from its tile rows.
        if (s->height != in_h && (in_h != 400 || s->height != 800)) continue;
        if (!src || s->last_used >= src->last_used) {
            source_row = row;
            src = s.get();
        }
    }""")
    source = replace(source, "    flush();\n    uint32_t hs =",
        """    if (top) {
        packed_scanout = {};
        if (src->height == 800 && in_h == 400)
            packed_scanout = {src->addr, int(source_row * src->scale),
                              int((source_row + in_h) * src->scale)};
    }
    flush();
    if ((source_row || src->height != in_h) && overwritten(src)) {
        if (top) end_interp_frame();
        return false;
    }
    uint32_t hs =""")
    source = replace(source,
        "    int w = int(src->th >> vs), h = int(src->tw >> hs); // upright: rows of the output become columns\n    (void)out_w, (void)out_h;",
        """    const int scale = src->scale;
    const int w = int(out_h >> vs) * scale;
    const int h = int(out_w >> hs) * scale;""")
    source = replace(source, "int32_t(hs), int32_t(vs), 0}};",
        "int32_t(hs), int32_t(vs), (int(source_row) + src->margin) * scale}};")
    source = replace(source, "std::atomic<uint64_t> vblanks{0};",
        "std::atomic<uint64_t> vblanks{0};\nstd::atomic<unsigned> interpolated_presentations{0};")
    source = replace(source, "    q.latest = q.ready.front();", """    if (q.latest != q.ready.front()) ++interpolated_presentations;
    q.latest = q.ready.front();""")
    source = replace(source, "SDL_GPUTexture *top_frame(int *width, int *height) {",
        """unsigned take_interpolated_presentations() { return interpolated_presentations.exchange(0); }

SDL_GPUTexture *top_frame(int *width, int *height) {""")
    return replace(source, "    k.color_mask = regs[COLOR_WRITE_ALLOW] ? uint8_t((dm >> 8) & 0xF) : 0;",
        """    const bool preserve_color = !k.blend && (regs[LOGIC_OP] & 0xF) == 6;
    // PICA NoOp preserves the destination color while depth and stencil still update.
    k.color_mask = regs[COLOR_WRITE_ALLOW] && !preserve_color ? uint8_t((dm >> 8) & 0xF) : 0;""")


def scale_gpu_targets(source):
    source = replace(source, "std::vector<std::unique_ptr<Surface>> surfaces;",
                     "std::vector<std::unique_ptr<Surface>> surfaces;\nint render_scale = 1, render_margin = 0;")
    source = replace(source, "    int margin, scale;\n    requested_enhancement(&margin, &scale);",
                     "    int margin = render_margin;\n    const int scale = render_scale;")
    source = replace(source, "void begin_list() {\n    list_hashes.clear();", """void begin_list() {
    list_hashes.clear();
    int scale;
    requested_enhancement(&render_margin, &scale);
    if (scale != render_scale) {
        // Keep guest-visible pixels when replacing targets, including off-screen textures.
        flush();
        for (const auto &s : surfaces) {
            if (!s->depth && s->drawn && !s->reload && !overwritten(s.get())) download_surface(s.get());
        }
        release_twins();
        for (const auto &s : surfaces) SDL_ReleaseGPUTexture(dev, s->tex);
        surfaces.clear();
        last_frame.clear();
        this_frame.clear();
        packed_scanout = {};
        interp_this = false;
        render_scale = scale;
    }""")
    source = replace(source, "SDL_Mutex *lcd_lock;", "SDL_Mutex *lcd_lock;\nstd::vector<SDL_GPUTexture *> retired_scanouts;")
    for frame, indent in (("f", "        "), ("q", "            ")):
        source = replace(source, f"{indent}for (auto *t : {frame}.tex)\n{indent}    if (t) SDL_ReleaseGPUTexture(dev, t);",
                         f"{indent}for (auto *t : {frame}.tex)\n{indent}    if (t) retired_scanouts.push_back(t);")
    source = replace(source, "    lcd.erase(addr); // an LCD buffer written by the CPU shows that, not an older GPU frame",
        """    if (auto it = lcd.find(addr); it != lcd.end()) {
        for (auto *texture : it->second.tex)
            if (texture) retired_scanouts.push_back(texture);
        lcd.erase(it);
    }""")
    source = replace(source, "SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {",
        """std::vector<SDL_GPUTexture *> take_retired_scanouts() {
    std::vector<SDL_GPUTexture *> result;
    if (!ok) return result;
    SDL_LockMutex(lcd_lock);
    result.swap(retired_scanouts);
    SDL_UnlockMutex(lcd_lock);
    return result;
}

SDL_GPUTexture *lcd_frame(uint32_t addr, int *width, int *height) {""")
    # The main thread can be inside the native menu while command lists continue.
    source = source.replace("SDL_SubmitGPUCommandBuffer(cmd);", "submit_commands(cmd);")
    source = replace(source, "// Copies a surface's image back into guest memory", """void submit_commands(SDL_GPUCommandBuffer *cmd) {
    // Reclaim batches even while the window is blocked in a menu or resize loop.
    static unsigned submissions = 0;
    static SDL_GPUFence *previous = nullptr;
    if (++submissions < 64) {
        if (!SDL_SubmitGPUCommandBuffer(cmd)) fatal("Vulkan command submission failed: %s", SDL_GetError());
        return;
    }
    submissions = 0;
    auto *fence = SDL_SubmitGPUCommandBufferAndAcquireFence(cmd);
    if (!fence) fatal("Vulkan command submission failed: %s", SDL_GetError());
    if (previous) {
        if (!SDL_WaitForGPUFences(dev, true, &previous, 1)) fatal("Vulkan command wait failed: %s", SDL_GetError());
        SDL_ReleaseGPUFence(dev, previous);
    }
    previous = fence;
}

// Copies a surface's image back into guest memory""")
    source = replace(source, """    Surface *bc = nullptr, *bd = nullptr;
    for (const DrawRec &d : batch) {
        begin_render_pass(cmd, pass, bc, bd, d.color, d.depth);
        d.color->drawn = true;
        SDL_BindGPUGraphicsPipeline(pass, d.pipeline);""",
        """    Surface *bc = nullptr, *bd = nullptr;
    SDL_GPUGraphicsPipeline *pipeline = nullptr;
    for (const DrawRec &d : batch) {
        if (!pass || bc != d.color || bd != d.depth) {
            begin_render_pass(cmd, pass, bc, bd, d.color, d.depth);
            SDL_GPUBufferBinding binding{vbuf, 0};
            SDL_BindGPUVertexBuffers(pass, 0, &binding, 1);
            pipeline = nullptr;
        }
        d.color->drawn = true;
        if (pipeline != d.pipeline) {
            SDL_BindGPUGraphicsPipeline(pass, d.pipeline);
            pipeline = d.pipeline;
        }""")
    return replace(source, "        SDL_GPUBufferBinding vb{vbuf, 0};\n        SDL_BindGPUVertexBuffers(pass, 0, &vb, 1);\n", "")


def texture_decode(source):
    return replace(source, "void decode_texture(const Texture &t, uint8_t *rgba) {",
        """void decode_texture(const Texture &t, uint8_t *rgba) {
    if ((t.format == T_ETC1 || t.format == T_ETC1A4) && ((t.width | t.height) & 7) == 0) {
        // Load each compressed block once. Keep the original PICA color and alpha decoding.
        const bool alpha = t.format == T_ETC1A4;
        const uint32_t block_size = alpha ? 16 : 8;
        const uint8_t *block = t.data;
        for (uint32_t y = 0; y < t.height; y += 8)
            for (uint32_t x = 0; x < t.width; x += 8)
                for (uint32_t dy = 0; dy < 8; dy += 4)
                    for (uint32_t dx = 0; dx < 8; dx += 4, block += block_size) {
                        uint64_t colors, alphas = UINT64_MAX;
                        if (alpha) std::memcpy(&alphas, block, sizeof alphas);
                        std::memcpy(&colors, block + (alpha ? 8 : 0), sizeof colors);
                        for (uint32_t row = 0; row < 4; ++row) {
                            auto *out = rgba + (size_t(y + dy + row) * t.width + x + dx) * 4;
                            for (uint32_t col = 0; col < 4; ++col) {
                                Rgba pixel = etc1(colors, col, row);
                                pixel.a = expand4(uint32_t(alphas >> (4 * (4 * col + row))) & 15);
                                std::memcpy(out + col * 4, &pixel, 4);
                            }
                        }
                    }
        return;
    }""")


def video_commands(source):
    source = replace(source, "            if (table < 24) lighting_lut[table][at & 0xFF] = value, lighting_lut_version++;",
        """            if (table < 24) {
                auto &entry = lighting_lut[table][at & 0xFF];
                // The game often uploads the current lighting table again.
                // The renderer only needs to flush when its contents change.
                if (entry != value) {
                    entry = value;
                    ++lighting_lut_version;
                }
            }""")
    source = replace(source, '"cull=%u depth=%x scissor=%u tex0=%08x %ux%u f%u blend=%u mask=%x vs=%x\\n",',
        '"cull=%u depth=%x scissor=%u tex0=%08x %ux%u f%u type=%u mode=%x op=%x logic=%x mask=%x vs=%x\\n",')
    source = replace(source,
        '(regs[COLOR_OP] >> 8) & 1, (regs[DEPTH_COLOR_MASK] >> 8) & 0xF, regs[VS_ENTRY] & 0xFFFF);',
        '''(regs[TEX0_PARAM] >> 28) & 7, regs[COLOR_FORMAT], regs[COLOR_OP], regs[0x102],
                  (regs[DEPTH_COLOR_MASK] >> 8) & 0xF, regs[VS_ENTRY] & 0xFFFF);''')
    source = replace(source, "        if (draw_log_state == 2) {\n            if (FILE *f",
        "        if (draw_log_state == 2 && !draw_log_text.empty()) {\n            if (FILE *f")
    return vertex_workers(pica(source))


def filesystem(source):
    source = source.replace("    bool romfs = false, update = false;",
                            "    bool romfs = false, update = false, read_only = false;")
    source = source.replace("            if (romfs) {\n                req.reply(1, 0, ERR_UNSUPPORTED);",
                            "            if (romfs || read_only) {\n                req.reply(1, 0, ERR_UNSUPPORTED);")
    source = source.replace("            if (!romfs) {\n                host.flush();",
                            """            if (romfs || read_only) {
                req.reply(1, 0, ERR_UNSUPPORTED);
                break;
            }
            {
                host.flush();""")
    source = source.replace("        case SELF_NCCH:\n        case NCCH:",
                            """        case NCCH: {
            uint64_t title = 0;
            if (path.data.size() >= sizeof title) std::memcpy(&title, path.data.data(), sizeof title);
            if (title == 0x0004009b00010202ull) {
                const char *base = SDL_GetBasePath();
                auto image = std::filesystem::path(base ? base : ".") / "mii.romfs";
                if (!fs::is_regular_file(image)) {
                    LOG("fs: missing Mii resource archive %s; rerun the build command", image.string().c_str());
                    return ERR_ARCHIVE_NOT_FOUND;
                }
                LOG("fs: opened read-only Mii resource archive");
                *out = {id, image};
                return kernel::RESULT_OK;
            }
            if (title != dump().program_id()) return ERR_ARCHIVE_NOT_FOUND;
            *out = {id, {}};
            return kernel::RESULT_OK;
        }
        case SELF_NCCH:""")
    source = source.replace("        auto f = std::make_shared<File>();\n        if (a.root.empty()) {",
                            """        auto f = std::make_shared<File>();
        if (a.id == NCCH && !a.root.empty()) {
            if (flags != 1 || path.type != PATH_BINARY || path.data.size() != 20 ||
                std::any_of(path.data.begin(), path.data.end(), [](uint8_t b) { return b != 0; }))
                return ERR_FILE_NOT_FOUND;
            f->host_path = a.root;
            f->host.open(a.root, std::ios::binary | std::ios::in);
            if (!f->host) return ERR_FILE_NOT_FOUND;
            f->read_only = true;
            *out = f;
            return kernel::RESULT_OK;
        }
        if (a.root.empty()) {""")
    return source.replace('#include "service.h"', '#include "service.h"\n#include <SDL3/SDL.h>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    transforms = {
        "src/frontend/sdl.cpp": frontend,
        "src/frontend/frontend.h": lambda text: replace(replace(replace(replace(
            text, "#pragma once", "#pragma once\n#include <vector>"),
            "const char *cli_dump, bool force_launcher, bool play", "const char *cli_dump"),
            "    bool touching = false;",
            "    int16_t accel[3] = {0, -512, 0};\n    int16_t gyro[3] = {};\n    bool touching = false;"),
            "Input input();", "Input input();\nint verify_gamepad();\nint poll_gamepad();\n"
            "void finish_scanout(const std::vector<SDL_GPUTexture *> &retired);"),
        "src/frontend/settings.h": lambda text: replace(replace(text,
            "int volume = 100;", "int volume = 25;"), "int hud_size = 80;", "int hud_size = 100;"),
        "src/frontend/settings.cpp": lambda text: replace(text,
            '        else if (k == "resolution") resolution = std::atoi(v.c_str());',
            '''        else if (k == "resolution") {
            const int scale = std::atoi(v.c_str());
            resolution = scale == 2 || scale == 4 ? scale : 1;
        }'''),
        "src/frontend/games.h": lambda text: replace(text, "inline constexpr KnownDump KNOWN_DUMPS[] = {",
            'inline constexpr KnownDump KNOWN_DUMPS[] = {\n'
            '    {0x000400000010C000, "kirby", "", "KirbyTripleDeluxe", Region::EUR},'),
        "src/platform.cpp": platform,
        "src/hle/apt.cpp": applets,
        "src/hle/cfg.cpp": console_settings,
        "src/hle/gsp.cpp": display_statistics,
        "src/hle/hid.cpp": motion_service,
        "src/hle/service.cpp": local_services,
        "src/hle/stubs.cpp": loader_service,
        "src/hle/fs.cpp": filesystem,
        "src/hle/err.cpp": lambda text: replace(text,
            "name, w[2], w[3], w[6], w[5]", "name, w[1], w[2], w[6], w[5]"),
        "src/video/pica.cpp": video_commands,
        "src/video/pica.h": lambda text: replace(text,
            "uint32_t in_dims, uint32_t out_dims, uint32_t flags);",
            "uint32_t in_dims, uint32_t out_dims, uint32_t flags, bool right_eye = false);"),
        "src/video/transfer.cpp": display_transfer,
        "src/video/gpu/gpu.cpp": lambda text: scale_gpu_targets(reuse_upload_buffer(vulkan_renderer(text))),
        "src/video/gpu/gpu.h": lambda text: replace(replace(replace(text,
            "#include <cstdint>", "#include <cstdint>\n#include <vector>"),
            "uint32_t flags);", "uint32_t flags, bool right_eye);"),
            "void vblank();", "void vblank();\nunsigned take_interpolated_presentations();\n"
            "std::vector<SDL_GPUTexture *> take_retired_scanouts();"),
        "src/video/shader.cpp": shader,
        "src/video/texture.cpp": texture_decode,
        "src/log.cpp": call_trace,
        "src/kernel/kernel.cpp": kernel_dispatch,
        "include/recomp.h": translation_contract,
    }
    for tree in ("src", "include"):
        for source in (args.upstream / tree).rglob("*"):
            if not source.is_file():
                continue
            key = source.relative_to(args.upstream).as_posix()
            output = args.output / key
            output.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix not in (".cpp", ".c", ".h"):
                if not output.is_file() or output.read_bytes() != source.read_bytes():
                    shutil.copy2(source, output)
                continue
            text = source.read_text(encoding="utf-8")
            if key in transforms:
                text = transforms[key](text)
            text = text.replace('"YW2_', '"KIRBY_')
            if not output.is_file() or output.read_text(encoding="utf-8") != text:
                output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
