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

# The player's copy: the www/ folder of the RPG Maker MV/MZ game
if [ ! -f "$GAMEDIR/gamedata/www/index.html" ]; then
  pm_message "Copy the www folder of your copy of <Game> into ports/portfolder/gamedata and launch again."
  sleep 5
  pm_finish
  exit 1
fi

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
# quixjs' own launcher menu draws with this font
export QUIXJS_FONT="$GAMEDIR/fonts/DejaVuSans-Bold.ttf"
chmod +x "$GAMEDIR/quixjs.${DEVICE_ARCH}"

# quixjs reads the pad itself: gptokeyb2 only provides the hotkey exit (leave $HOTKEY to control.txt)
$GPTOKEYB2 "quixjs.${DEVICE_ARCH}" &
pm_platform_helper "$GAMEDIR/quixjs.${DEVICE_ARCH}"
./quixjs.${DEVICE_ARCH} --launcher -c port.toml

pm_finish

