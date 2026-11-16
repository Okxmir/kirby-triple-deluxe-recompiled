"""Prepare ARM function discovery from the pinned Clockwork recompiler."""

import argparse
import shutil
from pathlib import Path

from prepare_runtime import replace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    shutil.copytree(args.upstream, args.output, dirs_exist_ok=True)
    path = args.output / "discover.rs"
    text = replace(path.read_text(encoding="utf-8"),
        "        Op::Udf | Op::Bkpt(_) => Flow::Stop,",
        "        Op::Udf | Op::Bkpt(_) if !conditional => Flow::Stop,")
    text = replace(text, "                    Op::BranchReg { rm, .. } => self.resolve(&e.f, site, rm, 0),",
        """                    // Thumb BX PC is an interworking veneer for the following ARM code.
                    Op::BranchReg { rm: PC, link: false } if insn.thumb =>
                        Some(Value::Const((site + 4) & !3)),
                    Op::BranchReg { rm, .. } => self.resolve(&e.f, site, rm, 0),""")
    text = replace(text, "        d.add_entry(image.text.addr, false);",
        """        d.add_entry(image.text.addr, false);
        // Kirby EUR's initializer at 0x005afc0c walks relative function pointers.
        // Each word is added to its own address before the ARM branch at 0x005afc30.
        let start = 0x005afc1cu32.wrapping_add(image.u32(0x005afc44).unwrap());
        let end = 0x005afc24u32.wrapping_add(image.u32(0x005afc48).unwrap());
        assert_eq!((start, end), (0x005afc4c, image.text.addr + image.text.size));
        for slot in (start..end).step_by(4) {
            let address = slot.wrapping_add(image.u32(slot).unwrap());
            assert!(address >= image.text.addr && address < start && address & 3 == 0);
            d.add_entry(address, false);
        }""")
    path.write_text(text, encoding="utf-8")

    path = args.output / "emit.rs"
    text = path.read_text(encoding="utf-8")
    text = replace(text, '            Exit::Goto(t) if f.insns.contains_key(&t) => format!("goto {};", label(t)),',
        """            Exit::Goto(t) if f.insns.contains_key(&t) => {
                if t <= site {
                    format!("recomp_poll_guest(ctx); goto {};", label(t))
                } else {
                    format!("goto {};", label(t))
                }
            },""")
    text = replace(text, '        writeln!(out, "    RECOMP_ENTER(ctx, 0x{:08x}u);", f.entry).unwrap();',
        '        writeln!(out, "    RECOMP_ENTER(ctx, 0x{:08x}u); recomp_poll_guest(ctx);", f.entry).unwrap();')
    text = replace(text, "            // guest threads only switch at SVCs, so exclusive pairs can't be interrupted\n", "")
    text = replace(text, """                match size {
                    MemSize::Dual => writeln!(o, "ctx->r[{rt}] = rd32({a}); ctx->r[{}] = rd32({a} + 4);", rt + 1).unwrap(),""",
        """                writeln!(o, "uint32_t exclusive_address = {a};").unwrap();
                let kind = *size as u32 + 1;
                writeln!(o, "ctx->exclusive_address = exclusive_address; ctx->exclusive_kind = {kind};").unwrap();
                let a = "exclusive_address";
                match size {
                    MemSize::Dual => writeln!(o, "ctx->r[{rt}] = rd32({a}); ctx->r[{}] = rd32({a} + 4);", rt + 1).unwrap(),""")
    text = replace(text, """                let a = rd(*rn);
                match size {
                    MemSize::Dual => writeln!(o, "wr32({a}, {}); wr32({a} + 4, {});", rd(*rt), rd(rt + 1)).unwrap(),""",
        """                let a = rd(*rn);
                let kind = *size as u32 + 1;
                writeln!(o, "if (ctx->exclusive_kind == {kind} && ctx->exclusive_address == {a}) {{").unwrap();
                match size {
                    MemSize::Dual => writeln!(o, "wr32({a}, {}); wr32({a} + 4, {});", rd(*rt), rd(rt + 1)).unwrap(),""")
    text = replace(text, """                writeln!(o, "ctx->r[{d}] = 0;").unwrap();
            }
            Op::Clrex | Op::Pld | Op::Hint(_) => {}""",
        """                writeln!(o, "ctx->r[{d}] = 0; }} else {{ ctx->r[{d}] = 1; }}").unwrap();
                writeln!(o, "ctx->exclusive_kind = 0;").unwrap();
            }
            Op::Clrex => writeln!(o, "ctx->exclusive_kind = 0;").unwrap(),
            Op::Pld | Op::Hint(_) => {}""")
    text = replace(text, 'format!("{}(ctx); return;", fn_name(t))',
                   'format!("ctx->pending_tail = {}; return;", fn_name(t))')
    text = replace(text, 'format!("recomp_call_indirect(ctx, 0x{t:08x}u); return;")',
                   'format!("recomp_tail_indirect(ctx, 0x{t:08x}u); return;")')
    text = replace(text, 'format!("recomp_call_indirect(ctx, {v}); return;")',
                   'format!("recomp_tail_indirect(ctx, {v}); return;")')
    # BL, statically resolved BLX, and calls with a manually assigned return address
    if text.count('writeln!(o, "{}(ctx);",') != 3:
        raise ValueError("Unexpected direct-call emission sites")
    text = text.replace('writeln!(o, "{}(ctx);",', 'writeln!(o, "{}(ctx); recomp_follow_tail(ctx);",')
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
