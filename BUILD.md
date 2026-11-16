# Building Kirby: Triple Deluxe

The Windows build uses a locally owned, decrypted European Nintendo 3DS cartridge image with product code `CTR-P-BALP` and program ID `000400000010C000`. The build checks that the original code matches the supported revision before it compiles.

## Requirements

- Windows 10 or 11 x64.
- Visual Studio or Build Tools with **Desktop development with C++**, including a Windows SDK and the CMake tools for Windows.
- Python 3.11 or newer with pip. The `python` command must work in Command Prompt.
- Internet access to download the pinned build dependencies on the first run.

Open this project folder in File Explorer. Type `cmd` in the address bar and press Enter. Run the command with your cartridge filename or its full path.

```cmd
build.cmd -Cartridge "YourCartridge.3ds" -Language en
```

After a successful build, open `dist\KirbyTripleDeluxe.exe`. Keep `extracted\KIRBY-EUR.cxi` in the project folder so the game can find its local data. Save data is stored in `dist\userdata`.

The language codes are `en` for English, `fr` for French, `de` for German, `es` for Spanish, and `it` for Italian. Omitting `-Language` keeps the current language in an existing profile. Use `-Fast` for a shorter development build with guest code optimization disabled.

## Individual steps

From Command Prompt in the project folder, run each step in order. Continue once the previous command succeeds.

```cmd
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\prepare.ps1" -Cartridge "YourCartridge.3ds"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\prepare_font.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_release.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_tests.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\package.ps1" -Language en
```

For a Debug build, use `scripts/build_debug.ps1` and `scripts/run_tests.ps1 -Configuration Debug`. Run `KirbyTripleDeluxe.exe --verify-gamepad` to check the standard SDL controller mapping with a virtual controller.
