# Kirby: Triple Deluxe Recompiled

An experimental Windows x64 and Linux x86-64 port of the European Nintendo 3DS release. The build recompiles the original ARM code and plays it using local cartridge data, with Vulkan rendering and a software fallback.

## Windows

Open the project folder in File Explorer, type `cmd` in the address bar, and press Enter. Run this command with the path to your decrypted European cartridge image.

```cmd
build.cmd -Cartridge "YourCartridge.3ds" -Language en
```

Open `dist\KirbyTripleDeluxe.exe` after the build passes its tests. Set `-Language en` for English, `fr` for French, `de` for German, `es` for Spanish, or `it` for Italian. See [BUILD.md](BUILD.md) for requirements and individual build steps.

## Linux

Install the dependencies in [BUILD.md](BUILD.md#linux-x86-64), then run these commands in the project folder.

```bash
bash build.sh --cartridge "YourCartridge.3ds" --language en
./dist/linux-x64/KirbyTripleDeluxe
```

The Linux build uses the same language codes with `--language`.

## Display and controls

With Vulkan enabled, use the **Upscaling** menu below the window title to switch between **1×**, **2×**, and **4×** while playing. The game saves the choice in `dist\userdata\settings.ini`. **1×** renders at the original Nintendo 3DS resolution.

| Action | Keyboard | Controller |
| --- | --- | --- |
| Move | Arrow keys or physical WASD | Left stick or D-pad |
| Jump / Confirm | K | Right face button |
| Inhale / Cancel | J | Bottom face button |
| Guard | Q or E | Shoulder buttons |
| Pause | Enter | Start |
| Touchscreen | Click the lower screen | |
| Tilt | T / G | Right stick or motion sensors |
| Fullscreen | F11 | |

The first play session creates a save in the `userdata` folder beside the executable. Controller input uses SDL's gamepad mapping.
