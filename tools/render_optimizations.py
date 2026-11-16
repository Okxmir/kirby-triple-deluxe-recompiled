"""Vertex shader and worker improvements shared with the Mario port."""


def between(source, start, end):
    left = source.index(start)
    return source[left:source.index(end, left)]


def pica(source):
    source = source.replace('#include "gpu/gpu.h"', '#include "gpu/gpu.h"\n#include "pica_shader_jit.h"')
    source = source.replace("ShaderSetup vs;", "ShaderSetup vs;\nstatic uint64_t shader_revision = 0;")
    source = source.replace("            vs.code[at & 4095] = value;",
                            """            auto &word = vs.code[at & 4095];
            if (word != value) ++shader_revision;
            word = value;""")
    source = source.replace("            vs.swizzle[at & 127] = value;",
                            """            auto &word = vs.swizzle[at & 127];
            if (word != value) ++shader_revision;
            word = value;""")
    source = source.replace("Vertex shade(const Vec4 attrs[16], const OutputMap &map) {",
                            "Vertex shade(const Vec4 attrs[16], const OutputMap &map, CompiledVertex compiled = nullptr) {")
    source = source.replace("    run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);",
                            """    if (compiled) {
        // Generated code supplies zero for unwritten temporaries.
        Vec4 scratch[16];
        compiled(vs.f, in, out, scratch);
        static const bool verify = std::getenv("KIRBY_VERIFY_VERTEX") != nullptr;
        if (verify) {
            Vec4 expected[16]{};
            run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, expected);
            if (std::memcmp(expected, out, sizeof out) != 0)
                fatal("Vertex shader output differs at %#x", regs[VS_ENTRY] & 0xFFFF);
        }
    } else {
        run_shader(vs, regs[VS_ENTRY] & 0xFFFF, in, out);
    }""")
    source = source.replace("    OutputMap map;\n", """    OutputMap map;
    static const bool interpret = std::getenv("KIRBY_INTERPRET_VERTEX") != nullptr;
    const auto compiled = interpret ? nullptr : find_compiled_shader(vs, regs[VS_ENTRY] & 0xFFFF, shader_revision);
""")
    source = source.replace("    int8_t semantic[16][4];\n    uint32_t mask;",
                            """    struct Component { uint8_t reg, channel, semantic; };
    Component components[28]{};
    uint32_t component_count = 0;
    uint8_t input_registers[16]{};
    uint32_t input_count = 0;""")
    source = source.replace("        std::memset(semantic, -1, sizeof semantic);\n        mask = regs[VS_OUTPUT_MASK] & 0xFFFF;",
                            """        const uint32_t mask = regs[VS_OUTPUT_MASK] & 0xFFFF;
        input_count = (regs[VS_INPUT_CONFIG] & 0xF) + 1;
        const uint64_t input_map = regs[VS_INPUT_MAP_LO] | (uint64_t(regs[VS_INPUT_MAP_HI]) << 32);
        for (uint32_t i = 0; i < input_count; ++i)
            input_registers[i] = uint8_t((input_map >> (4 * i)) & 0xF);""")
    source = source.replace("                semantic[reg][c] = sem < SEMANTIC_COUNT ? int8_t(sem) : -1;",
                            "                if (sem < SEMANTIC_COUNT)\n"
                            "                    components[component_count++] = {uint8_t(reg), uint8_t(c), uint8_t(sem)};")
    source = source.replace(
        between(source, "    uint32_t inputs = (regs[VS_INPUT_CONFIG]", "    if (compiled)"),
        "    for (uint32_t i = 0; i < map.input_count; ++i) in[map.input_registers[i]] = attrs[i];\n")
    source = source.replace(
        between(source, "    for (int r = 0; r < 16; r++)", "    // colors are clamped"),
        """    for (uint32_t i = 0; i < map.component_count; ++i) {
        const auto &component = map.components[i];
        v.a[component.semantic] = out[component.reg][component.channel];
    }
""")
    source = source.replace(
        "            for (uint32_t c = 0; c < a.count; c++) {",
        """            if (a.type == 3) {
                // Float vertex arrays are common in 3DS meshes. Load exactly
                // the declared components, including tightly packed XYZ.
                switch (a.count) {
                    case 4: std::memcpy(v.v, p, 16); break;
                    case 3: std::memcpy(v.v, p, 12); break;
                    case 2: std::memcpy(v.v, p, 8); break;
                    default: std::memcpy(v.v, p, 4); break;
                }
                out[i] = v;
                continue;
            }
            for (uint32_t c = 0; c < a.count; c++) {""",
    ).replace("                default: std::memcpy(&v[c], p + 4 * c, 4);", "")
    source = source.replace(
        "        for (auto &e : cache) e.index = ~0u;",
        "        if (indexed) for (auto &e : cache) e.index = ~0u;",
    )
    source = source.replace("#include <cmath>", "#include <cmath>\n#include <immintrin.h>")
    source = source.replace(
        "    for (int c = 0; c < 4; c++) v.a[COLOR + c] = std::fmin(std::fabs(v.a[COLOR + c]), 1.0f);",
        """    const __m128 color = _mm_loadu_ps(v.a + COLOR);
    const __m128 magnitude = _mm_andnot_ps(_mm_set1_ps(-0.0f), color);
    // MINPS selects the second operand for NaN, matching fmin here.
    _mm_storeu_ps(v.a + COLOR, _mm_min_ps(magnitude, _mm_set1_ps(1.0f)));""",
    )
    source = source.replace(
        "    if (n >= 512) {",
        """    if (n >= 512 && !indexed) {
        // Sequential draws have no repeated indices to look up or restore.
        static std::vector<Vertex> shaded;
        if (shaded.size() < n) shaded.resize(n);
        const uint32_t first = regs[VERTEX_OFFSET];
        workers().run(n, [&](size_t begin, size_t end) {
            Vec4 attrs[16];
            for (size_t k = begin; k < end; ++k) {
                loader.read(first + uint32_t(k), attrs);
                shaded[k] = shade(attrs, map);
            }
        });
        for (const Vertex &v : shaded) assembler.push(v);
        w = shaded[n - 1].a[POS + 3];
    } else if (n >= 512) {""",
    )
    source = source.replace(
        "    void push(const Vertex &v) {",
        """    template <class VertexAt>
    void push_range(uint32_t count, VertexAt vertex_at) {
        const uint32_t topology = (regs[PRIMITIVE_CONFIG] >> 8) & 3;
        uint32_t i = 0;
        if (topology != 1 && topology != 2 && list_count == 0) {
            // Complete lists can be emitted directly from the shaded vertices.
            for (; count - i >= 3; i += 3)
                emit_triangle(vertex_at(i), vertex_at(i + 1), vertex_at(i + 2));
        }
        for (; i < count; ++i) push(vertex_at(i));
    }

    void push(const Vertex &v) {""",
    ).replace(
        "        for (const Vertex &v : shaded) assembler.push(v);",
        "        assembler.push_range(n, [&](uint32_t i) -> const Vertex & { return shaded[i]; });",
    ).replace(
        "        for (uint32_t i = 0; i < n; i++) assembler.push(shaded[size_t(slot[index_at(i)])]);",
        """        assembler.push_range(n, [&](uint32_t i) -> const Vertex & {
            return shaded[size_t(slot[index_at(i)])];
        });""",
    ).replace(
        "        shaded.resize(unique.size());",
        "        if (shaded.size() < unique.size()) shaded.resize(unique.size());",
    ).replace(
        "        if (!shaded.empty()) w = shaded.back().a[POS + 3];",
        "        if (!unique.empty()) w = shaded[unique.size() - 1].a[POS + 3];",
    )
    return source.replace("shade(attrs, map)", "shade(attrs, map, compiled)")


def shader(source):
    source = source.replace('#include "log.h"', '#include "log.h"\n#include "pica_shader_arithmetic.h"')
    source = source.replace(between(source, "// 0 * anything", "struct Frame"), "")
    source = source.replace(between(source, "    static const Vec4 ones", "    auto evaluate"), "")
    source = source.replace("    int32_t addr[3] = {0, 0, 0}; // a0.x, a0.y, aL",
                            "    int32_t addr[4] = {}; // constant zero, a0.x, a0.y, aL")
    source = source.replace("addr[2] += f.increment;", "addr[3] += f.increment;")
    source = source.replace("addr[2] = iu[1];", "addr[3] = iu[1];")
    return source.replace(between(source, "        // arithmetic:", "        // flow control"),
                          """        if (op < 0x20 || op >= 0x2E) {
            run_arithmetic(s, pc, ins, in, out, tmp, addr, cond);
            ++pc;
            continue;
        }

""")


def vertex_workers(source):
    source = source.replace("#include <thread>", """#include <thread>
#ifdef _WIN32
#include <bit>
#include <windows.h>
#else
#include <sched.h>
#endif""")
    source = source.replace(
        "        unsigned hw = std::thread::hardware_concurrency();",
        """        unsigned hw = std::thread::hardware_concurrency();
#ifdef _WIN32
        DWORD_PTR allowed = 0, system = 0;
        if (GetProcessAffinityMask(GetCurrentProcess(), &allowed, &system) && allowed)
            hw = std::popcount(allowed);
#else
        cpu_set_t allowed;
        if (sched_getaffinity(0, sizeof allowed, &allowed) == 0 && CPU_COUNT(&allowed))
            hw = CPU_COUNT(&allowed);
#endif""",
    )
    source = source.replace("#include <condition_variable>", "#include <atomic>")
    source = source.replace(between(source, "        if (lanes == 1 || count < 64)", "    void slice("),
                            """        if (lanes == 1 || count < 256) return fn(0, count);
        job = &fn;
        job_count = count;
        pending.store(lanes - 1, std::memory_order_relaxed);
        generation.fetch_add(1, std::memory_order_release);
        generation.notify_all();
        slice(0, fn, count);
        for (int left = pending.load(std::memory_order_acquire); left;
             left = pending.load(std::memory_order_acquire))
            pending.wait(left, std::memory_order_acquire);
    }

private:
    int lanes = 1;
    std::atomic<int> pending{0};
    std::atomic<uint64_t> generation{0};
    size_t job_count = 0;
    const std::function<void(size_t, size_t)> *job = nullptr;

""")
    return source.replace(between(source, "        uint64_t seen = 0;", "\n};\n\nWorkers &workers"),
                          """        uint64_t seen = 0;
        for (;;) {
            generation.wait(seen, std::memory_order_acquire);
            seen = generation.load(std::memory_order_acquire);
            slice(lane, *job, job_count);
            if (pending.fetch_sub(1, std::memory_order_acq_rel) == 1) pending.notify_one();
        }
    }""")


def reuse_upload_buffer(source):
    source = source.replace(
        "// copies pending texture, LUT, surface and vertex data to the GPU (one copy pass)",
        """// Keep the transfer buffer across batches. SDL cycles its backing storage\n// when commands from an earlier batch still reference it.
SDL_GPUTransferBuffer *batch_upload = nullptr;
uint32_t upload_capacity = 0;

uint32_t batch_capacity(size_t size) {
    return uint32_t(std::min<uint64_t>(UINT32_MAX, std::max<uint64_t>(65536, uint64_t(size) * 2)));
}

// copies pending texture, LUT, surface and vertex data to the GPU (one copy pass)""")
    source = source.replace(
        """    SDL_GPUTransferBufferCreateInfo tbi{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, uint32_t(total), 0};
    SDL_GPUTransferBuffer *tb = SDL_CreateGPUTransferBuffer(dev, &tbi);
    if (!tb) out_of_gpu_memory(), tb = SDL_CreateGPUTransferBuffer(dev, &tbi);
    if (!tb) {""",
        """    if (total > upload_capacity && total <= UINT32_MAX) {
        SDL_GPUTransferBufferCreateInfo info{SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD, batch_capacity(total), 0};
        if (auto *larger = SDL_CreateGPUTransferBuffer(dev, &info)) {
            if (batch_upload) SDL_ReleaseGPUTransferBuffer(dev, batch_upload);
            batch_upload = larger;
            upload_capacity = info.size;
        }
    }
    SDL_GPUTransferBuffer *tb = total <= upload_capacity ? batch_upload : nullptr;
    auto *map = tb ? static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, true)) : nullptr;
    if (!map) {""")
    source = source.replace(
        "    auto *map = static_cast<uint8_t *>(SDL_MapGPUTransferBuffer(dev, tb, false));\n    size_t at = 0;",
        "    size_t at = 0;")
    source = source.replace("    SDL_EndGPUCopyPass(copy);\n    SDL_ReleaseGPUTransferBuffer(dev, tb);\n\n    // surface loads",
                            "    SDL_EndGPUCopyPass(copy);\n\n    // surface loads")
    return source
