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

# .NET 8 runtime from PortMaster (listed in port.json's "runtime")
dotnet_runtime="dotnet-8.0.12"
if [ ! -f "$controlfolder/libs/${dotnet_runtime}.squashfs" ]; then
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${dotnet_runtime}.squashfs"
fi
dotnet_dir=/tmp/dotnet8
$ESUDO mkdir -p "$dotnet_dir"
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
  $ESUDO umount "$dotnet_dir" 2>/dev/null
fi
$ESUDO mount "$controlfolder/libs/${dotnet_runtime}.squashfs" "$dotnet_dir"

mkdir -p "$GAMEDIR/conf"
bind_directories ~/.config/Studio/Game "$GAMEDIR/conf"

cd "$GAMEDIR/gamedata"
export DOTNET_ROOT="$dotnet_dir"
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
export FNA3D_FORCE_DRIVER=OpenGL
export FNA3D_OPENGL_FORCE_ES3=1

$GPTOKEYB2 "dotnet" &
pm_platform_helper "$dotnet_dir/dotnet"
"$dotnet_dir/dotnet" Game.dll

if [[ "$PM_CAN_MOUNT" != "N" ]]; then
  $ESUDO umount "$dotnet_dir"
fi
pm_finish

