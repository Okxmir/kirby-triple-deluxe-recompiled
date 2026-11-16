#include "dump.h"
#include "frontend/frontend.h"
#include "frontend/settings.h"
#include "game_code.h"
#include "kernel/kernel.h"
#include "loader.h"
#include "log.h"
#include "memory.h"

#include <SDL3/SDL.h>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include <openssl/sha.h>
#endif

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string_view>
#include <thread>

namespace game_code {
const RecompEntry *functions() { return recomp_functions; }
size_t function_count() { return recomp_function_count; }
}

namespace {
constexpr uint64_t title_id = 0x000400000010c000;
constexpr const char *partition = "KIRBY-EUR.cxi";
constexpr const char *cartridge_required =
    "Use your own decrypted European Kirby: Triple Deluxe cartridge image (CTR-P-BALP). "
    "Put the .3ds, .cci, or .cxi file next to the game executable or pass its path.";
constexpr std::array<uint8_t, 32> code_hash = {
    0xe3, 0xac, 0xd2, 0xfd, 0x3e, 0x6d, 0xc8, 0xed,
    0xde, 0x61, 0xa6, 0xf5, 0xba, 0xb0, 0xee, 0xd7,
    0xdf, 0x1d, 0xae, 0xeb, 0x02, 0xfd, 0x3c, 0x10,
    0xe4, 0x4a, 0xc4, 0x66, 0xe4, 0x77, 0x56, 0x7b,
};

#ifdef _WIN32
LONG WINAPI report_access_violation(EXCEPTION_POINTERS *exception) {
    const auto &record = *exception->ExceptionRecord;
    if (record.ExceptionCode != EXCEPTION_ACCESS_VIOLATION || record.NumberParameters < 2)
        return EXCEPTION_CONTINUE_SEARCH;
    const auto address = reinterpret_cast<const void *>(record.ExceptionInformation[1]);
    const auto pc = reinterpret_cast<uintptr_t>(record.ExceptionAddress);
    const auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    const auto op = record.ExceptionInformation[0];
    LOG("Windows access violation at host PC %p (image base %p), %s %p",
        reinterpret_cast<void *>(pc), reinterpret_cast<void *>(base),
        op == 0 ? "reading" : op == 1 ? "writing" : "executing", address);
    uint32_t guest = 0;
    if (recomp_mem && mem::guest_address(address, &guest)) LOG("Guest memory address %08x", guest);
    print_trace();
    std::fflush(stderr);
    if (std::getenv("KIRBY_NO_DIALOG")) std::_Exit(1);
    return EXCEPTION_CONTINUE_SEARCH;
}
#endif

std::filesystem::path find_local_cartridge(const std::filesystem::path &directory) {
    std::error_code error;
    const std::filesystem::directory_iterator end;
    std::filesystem::path image;
    for (std::filesystem::directory_iterator it(directory, error); !error && it != end; it.increment(error)) {
        const auto &path = it->path();
        if (!it->is_regular_file(error)) continue;
        const auto extension = path.extension().string();
        if (SDL_strcasecmp(extension.c_str(), ".3ds") != 0 &&
            SDL_strcasecmp(extension.c_str(), ".cci") != 0 &&
            SDL_strcasecmp(extension.c_str(), ".cxi") != 0) continue;
        if (peek_program_id(path) != title_id) continue;
        if (!image.empty()) return {};
        image = path;
    }
    return image;
}

std::filesystem::path pick_cartridge() {
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO)) fatal("%s\n\n%s", cartridge_required, SDL_GetError());
    struct Selection {
        std::atomic<bool> done{false};
        std::string path, error;
    } selection;
    static constexpr SDL_DialogFileFilter filters[] = {{"Decrypted 3DS cartridge images", "3ds;cci;cxi"}};
    SDL_ShowOpenFileDialog([](void *userdata, const char *const *files, int) {
        auto &result = *static_cast<Selection *>(userdata);
        if (!files) result.error = SDL_GetError();
        else if (*files) result.path = *files;
        result.done.store(true, std::memory_order_release);
    }, &selection, nullptr, filters, 1, nullptr, false);
    while (!selection.done.load(std::memory_order_acquire)) {
        SDL_PumpEvents();
        SDL_Delay(16);
    }
    SDL_QuitSubSystem(SDL_INIT_VIDEO);
    if (!selection.error.empty()) fatal("%s\n\nFile picker: %s", cartridge_required, selection.error.c_str());
    return std::filesystem::u8path(selection.path);
}

GameImage load(const char *path) {
    if (peek_program_id(path) != title_id)
        fatal("Expected a decrypted Kirby: Triple Deluxe European image (CTR-P-BALP): %s", path);
    open_dump(path);
    const auto &code = dump().code();
    if (code.size() != 0x52e000) fatal("Unexpected cartridge code size");
    std::array<uint8_t, 32> hash{};
#ifdef _WIN32
    const auto status = BCryptHash(BCRYPT_SHA256_ALG_HANDLE, nullptr, 0, const_cast<PUCHAR>(code.data()),
                                   static_cast<ULONG>(code.size()), hash.data(), static_cast<ULONG>(hash.size()));
    const bool hashed = status >= 0;
#else
    const bool hashed = SHA256(code.data(), code.size(), hash.data()) != nullptr;
#endif
    if (!hashed || hash != code_hash) fatal("The cartridge code does not match the European revision built here");
    mem::init();
    return load_game();
}

int verify_startup(const char *path) {
    const GameImage image = load(path);
    // The first BL in the cartridge entry point invokes this ARM routine.
    constexpr uint32_t address = 0x00100024;
    constexpr uint32_t start = 0x0062d704;
    constexpr uint32_t end = 0x00640368;
    if (image.data_end != start || image.bss_size != end - start)
        fatal("The cartridge has a different BSS layout");
    const auto first = game_code::functions();
    const auto last = first + game_code::function_count();
    const auto entry = std::lower_bound(first, last, address,
        [](const RecompEntry &item, uint32_t target) { return item.addr < target; });
    if (entry == last || entry->addr != address) fatal("The recompiled BSS initialization routine is missing");

    std::fill(mem::ptr(start), mem::ptr(end), uint8_t{0xa5});
    *mem::ptr(start - 1) = 0x4b;
    *mem::ptr(end) = 0x37;
    Ctx registers{};
    entry->fn(&registers);
    recomp_follow_tail(&registers);
    if (registers.r[0] != end || registers.r[1] != end ||
        *mem::ptr(start - 1) != 0x4b || *mem::ptr(end) != 0x37 ||
        !std::all_of(mem::ptr(start), mem::ptr(end), [](uint8_t value) { return value == 0; }))
        fatal("The recompiled startup routine did not reproduce the BSS clear");
    std::printf("Original startup function 0x%08x cleared %u bytes and preserved both boundary bytes\n",
                address, end - start);
    return 0;
}

void play(const char *path) {
    const auto image = load(path);
    kernel::init(image);
    if (std::getenv("KIRBY_TRACE_BOOT")) {
        std::thread([] {
            for (int sample = 1; sample <= 3; ++sample) {
                std::this_thread::sleep_for(std::chrono::seconds(5));
                LOG("Boot trace at %d seconds", sample * 5);
                kernel::dump_threads(stderr);
            }
        }).detach();
    }
    kernel::run(image);
}
}

int main(int argc, char **argv) {
#ifdef _WIN32
    SetUnhandledExceptionFilter(report_access_violation);
#endif
    log_cfg::init();
    if (argc == 2 && std::string_view(argv[1]) == "--verify-gamepad") return frontend::verify_gamepad();
    if (argc == 2 && std::string_view(argv[1]) == "--poll-gamepad") return frontend::poll_gamepad();
    if (argc == 3 && std::string_view(argv[1]) == "--verify-startup") return verify_startup(argv[2]);
    if (argc > 2 || (argc == 2 && std::string_view(argv[1]) == "--help")) {
        std::puts("KirbyTripleDeluxe [path to a decrypted European .3ds, .cci, or .cxi image]");
        return argc > 2 ? 2 : 0;
    }
    if (!std::getenv("KIRBY_NO_DIALOG")) {
        fatal_hook = [](const char *message) {
            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Kirby: Triple Deluxe", message, nullptr);
        };
    }
    const char *base = SDL_GetBasePath();
    const auto executable = std::filesystem::u8path(base ? base : ".");
    std::filesystem::path image;
    if (argc == 2) {
        image = argv[1];
    } else {
        for (const auto &directory : {executable, executable / ".." / "extracted",
                                     executable / ".." / ".." / "extracted"}) {
            image = directory / partition;
            if (std::filesystem::is_regular_file(image)) break;
            image.clear();
        }
        if (image.empty()) image = find_local_cartridge(executable);
        if (image.empty()) {
            auto &settings = frontend::settings();
            settings.load();
            if (!settings.game_path.empty() && peek_program_id(settings.game_path) == title_id)
                image = settings.game_path;
        }
        if (image.empty()) {
            if (std::getenv("KIRBY_NO_DIALOG")) fatal("%s", cartridge_required);
            image = pick_cartridge();
            if (image.empty()) return 0;
        }
    }
    if (!std::filesystem::is_regular_file(image)) fatal("Cartridge image not found: %s", image.string().c_str());
    frontend::run(play, image.string().c_str());
}
