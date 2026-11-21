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

# Ren'Py runtime from PortMaster (listed in port.json's "runtime")
runtime="renpy_8.3.4"
if [ ! -f "$controlfolder/libs/${runtime}.squashfs" ]; then
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${runtime}.squashfs"
fi
renpydir="$GAMEDIR/renpy"
$ESUDO mkdir -p "$renpydir"
$ESUDO umount "$renpydir" 2>/dev/null
$ESUDO mount "$controlfolder/libs/${runtime}.squashfs" "$renpydir"

# Ren'Py keeps saves in ~/.renpy
mkdir -p "$GAMEDIR/conf"
bind_directories ~/.renpy "$GAMEDIR/conf"

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
export PYTHONHOME="$renpydir"
export PYTHONPATH="$renpydir/lib/python3.9"
if [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then
  source "${controlfolder}/libgl_${CFW_NAME}.txt"
else
  source "${controlfolder}/libgl_default.txt"
fi

$GPTOKEYB2 "startRENPY" -c "./game.ini" &
pm_platform_helper "$renpydir/lib/py3-linux-aarch64/startRENPY"
"$renpydir/startRENPY" "$GAMEDIR/game"

if [[ "$PM_CAN_MOUNT" != "N" ]]; then
  $ESUDO umount "$renpydir"
fi
pm_finish

