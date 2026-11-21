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

# The player's copy of the game (x86_64 Linux build)
if [ ! -f "$GAMEDIR/gamedata/game.x86_64" ]; then
  pm_message "Copy the Linux version of <Game> into ports/portfolder/gamedata and launch again."
  sleep 5
  pm_finish
  exit 1
fi
chmod +x "$GAMEDIR/box64" "$GAMEDIR/gamedata/game.x86_64"

# Westonpack runtime (downloaded with the port when it is listed in port.json's "runtime")
weston_dir=/tmp/weston
weston_runtime="weston_pkg_0.2"
if [ ! -f "$controlfolder/libs/${weston_runtime}.squashfs" ]; then
  if [ ! -f "$controlfolder/harbourmaster" ]; then
    pm_message "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info."
    sleep 5
    exit 1
  fi
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${weston_runtime}.squashfs"
fi
$ESUDO mkdir -p "${weston_dir}"
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
  $ESUDO umount "${weston_dir}"
fi
$ESUDO mount "$controlfolder/libs/${weston_runtime}.squashfs" "${weston_dir}"

cd "$GAMEDIR/gamedata"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$GPTOKEYB2 "game.x86_64" -c "$GAMEDIR/game.ini" &
pm_platform_helper "$GAMEDIR/box64"

# box64 runs the x86_64 binary; libraries the game needs come from the port folder (never copied into the game files),
# a Steam stub is preloaded so it wins over the game's own libsteam_api.so
$ESUDO env CRUSTY_BLOCK_INPUT=1 \
  BOX64_LD_LIBRARY_PATH="$GAMEDIR/libs.x86_64" \
  BOX64_LD_PRELOAD="$GAMEDIR/libsteam_api.so" \
  $weston_dir/westonwrap.sh headless noop kiosk crusty_glx_gl4es \
  XDG_DATA_HOME="$GAMEDIR/conf" \
  "$GAMEDIR/box64" ./game.x86_64

# Stop Westonpack and unmount it
$ESUDO $weston_dir/westonwrap.sh cleanup
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
  $ESUDO umount "${weston_dir}"
fi
pm_finish

