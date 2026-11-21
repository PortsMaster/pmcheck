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
cd "$GAMEDIR/gamedata"

# Everything the script and the game print ends up in log.txt, the file testers send
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

# Mono runtime from PortMaster (downloaded with the port when listed in port.json's "runtime")
monodir="$HOME/mono"
monofile="$controlfolder/libs/mono-6.12.0.122-aarch64.squashfs"
if [ ! -f "$monofile" ]; then
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "mono-6.12.0.122-aarch64.squashfs"
fi
$ESUDO mkdir -p "$monodir"
$ESUDO umount "$monofile" || true
$ESUDO mount "$monofile" "$monodir"

# Saves live in the port folder
mkdir -p "$GAMEDIR/savedata"
bind_directories ~/.local/share/Game "$GAMEDIR/savedata"

# The game's bundled Windows/old Mono and FNA assemblies lose against the runtime's and the port's newer FNA in dlls/
rm -f System*.dll mscorlib.dll Mono.*.dll FNA.dll FNA.dll.config

export MONO_PATH="$GAMEDIR/dlls"
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$monodir/lib:$LD_LIBRARY_PATH"
export PATH="$monodir/bin:$PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
# FNA3D on the devices' GLES3
export FNA3D_FORCE_DRIVER=OpenGL
export FNA3D_OPENGL_FORCE_ES3=1

$GPTOKEYB2 "mono" &
pm_platform_helper "$monodir/bin/mono"
mono Game.exe

$ESUDO umount "$monodir"
pm_finish

