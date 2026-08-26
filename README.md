# Bookworm Adventures source launcher

This repository contains a small C host for the archived PopCap
`BookwormAdventures.dll`. It recreates the browser plugin's callbacks and
lifecycle messages, so this is the real game code and chapter data—not a static
HTML recreation.

## Run the source launcher

The staged files and isolated 32-bit Wine prefix are already prepared:

```sh
./run-native.sh
```

To rebuild the Windows launcher after editing its source:

```sh
./native/build.sh
cp native/bwa_launcher.exe runtime/stage/bwa_launcher.exe
./run-native.sh
```

The launcher sets its working directory to its own location, loads
`BookwormAdventures.dll`, supplies the six host callbacks requested by the DLL,
reproduces the archived page's `SessionReady`/`GameReady` handshake, and skips
the web page's between-chapter advertising break. Run the staged launcher via
`run-native.sh`; the build artifact in `native/` does not sit beside the game
assets and is not intended to be launched directly.

## Relevant files

- `native/bwa_launcher.c` — readable source for the replacement plugin host.
- `native/build.sh` — builds a 32-bit Windows executable with the local MinGW toolchain.
- `runtime/stage/` — staged DLL, properties, and chapter assets.
- `runtime/launcher-wineprefix/` — isolated Wine environment for this launcher.
- `bookwormadventures.js` and `common.js` — archived scripts used to recover the original lifecycle behavior.

## Browser status

`web/boxedwine/` is an experiment, not the working path. The current official
BoxedWine web build does not provide the Direct3D support this game needs, so
`index.html` should not be presented as a finished browser port. The proven
source-based path is the launcher above. A true browser delivery layer still
needs either a compatible emulator build, a source port of the rendering layer,
or server-side streaming of this working launcher.

The game files remain subject to their original rights and should only be
distributed where you have permission to do so.
