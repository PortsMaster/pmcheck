#!/bin/bash

XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}

if [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
  controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then
  controlfolder="$XDG_DATA_HOME/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi

export controlfolder

source $controlfolder/control.txt

export PORT_32BIT="Y" # If using a 32 bit port
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"

get_controls

GAMEDIR=/$directory/ports/portfolder/

cd $GAMEDIR
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export GMLOADER_DEPTH_DISABLE=1
export GMLOADER_SAVEDIR="$GAMEDIR/gamedata/"
export GMLOADER_PLATFORM="os_linux"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
$ESUDO chmod +x "$GAMEDIR/gmloader"

# if no .gptk file is used use $GPTOKEYB "gmloader" & 
$GPTOKEYB "gmloader" -c ./controls.gptk &
pm_platform_helper "gmloader"
./gmloader donor.apk

pm_finish

