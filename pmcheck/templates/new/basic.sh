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

# Saves and settings: point the game's own folder in $HOME into the port folder (create the target first)
mkdir -p "$GAMEDIR/conf/.portfolder"
bind_directories ~/.portfolder "$GAMEDIR/conf/.portfolder"

# Libraries the port ships (only those the CFWs lack) and the controller mapping for SDL
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

# gptokeyb2: the hotkey exit, plus key mappings from the .ini (drop -c when the game reads the pad itself)
$GPTOKEYB2 "portexecutable.${DEVICE_ARCH}" -c "./portexecutable.ini" &
# Closes PortMaster's message screen and hands the display to the game
pm_platform_helper "$GAMEDIR/portexecutable.${DEVICE_ARCH}"
./portexecutable.${DEVICE_ARCH}

# Stops gptokeyb and gives the screen back to the frontend
pm_finish
