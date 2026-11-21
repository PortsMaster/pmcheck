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

# First launch: PortMaster's patcher runs the port's setup with a progress screen. The script prints
# "PATCH_FAIL_MSG:<why>" and "Patching process failed!" when it fails; the patcher shows both.
if [ ! -f "$GAMEDIR/.setup_done" ]; then
  export PATCHER_FILE="$GAMEDIR/tools/patchscript"
  export PATCHER_GAME="<Game>"
  export PATCHER_TIME="a few minutes"
  chmod +x "$PATCHER_FILE"
  source "$controlfolder/utils/patcher.txt"
  cd $GAMEDIR
fi
if [ ! -f "$GAMEDIR/.setup_done" ]; then
  pm_message "<Game> is not set up yet: copy your game files into ports/portfolder/gamedata and launch again (log: patchlog.txt)."
  sleep 5
  pm_finish
  exit 1
fi

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
$GPTOKEYB2 "portexecutable.${DEVICE_ARCH}" &
pm_platform_helper "$GAMEDIR/portexecutable.${DEVICE_ARCH}"
./portexecutable.${DEVICE_ARCH}

pm_finish

