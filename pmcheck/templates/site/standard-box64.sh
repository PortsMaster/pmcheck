#!/bin/bash

XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}

# PortMaster sits in a different folder on each CFW: these four cover every supported one
if [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
  controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then
  controlfolder="$XDG_DATA_HOME/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi

# control.txt: device info ($DEVICE_ARCH, $CFW_NAME, $DISPLAY_WIDTH, $DEVICE_HAS_ARMHF ...), $ESUDO, $GPTOKEYB2, the pm_* helpers
source $controlfolder/control.txt
# mod_<CFW>.txt: the per-CFW fixes PortMaster maintains for every port (no CFW checks needed in the script)
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
# The device's SDL controller mapping, in $sdl_controllerconfig
get_controls

GAMEDIR=/$directory/ports/portfolder
cd $GAMEDIR

# Everything the script and the game print ends up in log.txt, the file testers send
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

# The player's copy of the game (the x86 Linux build)
if [ ! -f "$GAMEDIR/gamedata/game.x86_64" ]; then
  pm_message "Copy the Linux version of <Game> into ports/portfolder/gamedata and launch again."
  sleep 5
  pm_finish
  exit 1
fi
chmod +x "$GAMEDIR/box64/box64" "$GAMEDIR/gamedata/game.x86_64"

# box64 hands the game's SDL2 calls to the device's own SDL2. For desktop OpenGL the CFW's libgl file
# decides whether gl4es is needed (source it from $GAMEDIR, it looks for gl4es.* there)
if [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then
  source "${controlfolder}/libgl_${CFW_NAME}.txt"
else
  source "${controlfolder}/libgl_default.txt"
fi
if [ -n "$LIBGL_ES" ]; then
  export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.aarch64/libGL.so.1"
fi

# Native (aarch64) libraries for the calls box64 wraps, x86 libraries the game needs that box64 doesn't wrap
export LD_LIBRARY_PATH="$GAMEDIR/libs.aarch64:$LD_LIBRARY_PATH"
export BOX64_LD_LIBRARY_PATH="$GAMEDIR/libs.x86_64"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

# Saves and settings in the port folder (the game's own folder in $HOME)
mkdir -p "$GAMEDIR/conf"
bind_directories ~/.local/share/Game "$GAMEDIR/conf"

cd "$GAMEDIR/gamedata"
$GPTOKEYB2 "game.x86_64" -c "$GAMEDIR/game.ini" &
pm_platform_helper "$GAMEDIR/box64/box64"
"$GAMEDIR/box64/box64" ./game.x86_64

pm_finish

