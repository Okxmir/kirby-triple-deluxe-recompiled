"""Apply the Vulkan allocator workaround to the pinned SDL source."""

from pathlib import Path
import sys


def patch_vulkan_allocator(path):
    source = path.read_bytes()
    original = (
        b"        // No suitable free regions exist, allocate a new memory region\n"
        b"        if (\n"
    )
    patched = (
        b"        // No suitable free regions exist, allocate a new memory region\n"
        b"        // SDL #16685. Defrag can move a texture referenced\n"
        b"        // by another recorded command buffer. Keep free regions available\n"
        b"        // for reuse without queuing their allocations for relocation.\n"
        b"        const bool enableDefragmentation = false;\n"
        b"        if (enableDefragmentation &&\n"
    )
    if source.count(patched) == 1 and original not in source:
        return
    if source.count(original) != 1 or patched in source:
        raise SystemExit(f"Expected SDL 3.4.0 Vulkan allocator code in {path}")
    path.write_bytes(source.replace(original, patched, 1))


if __name__ == "__main__":
    patch_vulkan_allocator(Path(sys.argv[1]))
