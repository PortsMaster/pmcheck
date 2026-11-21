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

GAMEDIR=/$directory/ports/portfolder
cd $GAMEDIR

# Unity's 32-bit Android player is faster but needs the 32-bit userland with glibc 2.35 or newer;
# without it the 64-bit build. A build that is set up keeps its route.
if [ -f .setup_done ]; then ROUTE=32
elif [ -f .setup_done64 ]; then ROUTE=64
else
  ROUTE=64
  if [ "$DEVICE_HAS_ARMHF" = Y ]; then
    read -r major minor < <(/lib/ld-linux-armhf.so.3 --version 2>/dev/null | sed -n '1s/.*version \([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
    [ -n "$minor" ] && [ $((major * 1000 + minor)) -ge 2035 ] && ROUTE=32
  fi
fi
# Before mod_<CFW>.txt: it then sets up the 32-bit sound libraries (PipeWire in /usr/lib32)
[ "$ROUTE" = 32 ] && export PORT_32BIT="Y"
# mod_<CFW>.txt: the per-CFW fixes PortMaster maintains for every port (no CFW checks needed in the script)
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
# The device's SDL controller mapping, in $sdl_controllerconfig
get_controls

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1
if [ "$ROUTE" = 64 ]; then
  SETUP=patchscript64; READY=.setup_done64; HOST=ua_host64
else
  SETUP=patchscript; READY=.setup_done; HOST=ua_host
fi

# First launch: the setup converts the player's copy (PortMaster's patcher shows the progress)
if [ ! -f "$READY" ]; then
  export GAMEDIR controlfolder
  export PATCHER_FILE="$GAMEDIR/setup/$SETUP" PATCHER_GAME="<Game>" PATCHER_TIME="up to an hour, once"
  chmod +x "$PATCHER_FILE"
  source "$controlfolder/utils/patcher.txt"
  cd $GAMEDIR
fi
if [ ! -f "$READY" ]; then
  pm_message "<Game> is not set up yet: copy your game into ports/portfolder/gamedata and launch again (log: patchlog.txt)."
  sleep 5
  pm_finish
  exit 1
fi

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
chmod +x "$HOST"
# The game reads the pad itself: gptokeyb2 only provides the hotkey exit
$GPTOKEYB2 "$HOST" &
pm_platform_helper "$GAMEDIR/$HOST"
if [ "$ROUTE" = 64 ]; then
  ./ua_host64 "$GAMEDIR/arm64"
else
  # The 32-bit player's libraries live in /lib32 or /usr/lib32 on CFWs with a 32-bit userland
  LD_LIBRARY_PATH=/lib32:/usr/lib32:$LD_LIBRARY_PATH ./ua_host "$GAMEDIR"
fi

pm_finish

